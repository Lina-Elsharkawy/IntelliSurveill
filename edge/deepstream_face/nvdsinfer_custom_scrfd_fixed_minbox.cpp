
#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#include "nvdsinfer_custom_impl.h"

struct ScrfdDet {
    float x1;
    float y1;
    float x2;
    float y2;
    float score;
};

static const NvDsInferLayerInfo* findLayer(
    const std::vector<NvDsInferLayerInfo>& outputLayersInfo,
    const char* name)
{
    for (const auto& layer : outputLayersInfo) {
        if (layer.layerName && std::strcmp(layer.layerName, name) == 0) {
            return &layer;
        }
    }
    return nullptr;
}

static float clampf(float v, float lo, float hi)
{
    return std::max(lo, std::min(v, hi));
}

static float iou_xyxy(const ScrfdDet& a, const ScrfdDet& b)
{
    float xx1 = std::max(a.x1, b.x1);
    float yy1 = std::max(a.y1, b.y1);
    float xx2 = std::min(a.x2, b.x2);
    float yy2 = std::min(a.y2, b.y2);

    float w = std::max(0.0f, xx2 - xx1);
    float h = std::max(0.0f, yy2 - yy1);
    float inter = w * h;

    float areaA = std::max(0.0f, a.x2 - a.x1) * std::max(0.0f, a.y2 - a.y1);
    float areaB = std::max(0.0f, b.x2 - b.x1) * std::max(0.0f, b.y2 - b.y1);
    float uni = areaA + areaB - inter;

    if (uni <= 0.0f) return 0.0f;
    return inter / uni;
}

static void decodeLevel(
    const float* scores,
    const float* bbox,
    int featH,
    int featW,
    int stride,
    int numAnchors,
    float confThresh,
    int netW,
    int netH,
    std::vector<ScrfdDet>& dets)
{
    const int numLocations = featH * featW;
    const int totalAnchors = numLocations * numAnchors;

    for (int i = 0; i < totalAnchors; ++i) {
        float score = scores[i];

        // IMPORTANT:
        // The working Python detector uses scores directly.
        // It does NOT apply sigmoid.
        if (score < confThresh) {
            continue;
        }

        int loc = i / numAnchors;
        int y = loc / featW;
        int x = loc % featW;

        float cx = (static_cast<float>(x) + 0.5f) * static_cast<float>(stride);
        float cy = (static_cast<float>(y) + 0.5f) * static_cast<float>(stride);

        // Match Python:
        // bbox_preds = raw_bbox.reshape(-1, 4) * stride
        float l = bbox[i * 4 + 0] * static_cast<float>(stride);
        float t = bbox[i * 4 + 1] * static_cast<float>(stride);
        float r = bbox[i * 4 + 2] * static_cast<float>(stride);
        float b = bbox[i * 4 + 3] * static_cast<float>(stride);

        ScrfdDet d;
        d.x1 = clampf(cx - l, 0.0f, static_cast<float>(netW - 1));
        d.y1 = clampf(cy - t, 0.0f, static_cast<float>(netH - 1));
        d.x2 = clampf(cx + r, 0.0f, static_cast<float>(netW - 1));
        d.y2 = clampf(cy + b, 0.0f, static_cast<float>(netH - 1));
        d.score = score;

        if (d.x2 <= d.x1 + 2.0f || d.y2 <= d.y1 + 2.0f) {
            continue;
        }

        dets.push_back(d);
    }
}


// Min-box filter for production face pipeline.
// Coordinates are in SCRFD net space, 640x640.
// Net height 95 ~= 71 px in final 640x480 frame.
static const float SCRFD_MIN_NET_W = 90.0f;
static const float SCRFD_MIN_NET_H = 95.0f;

extern "C"
bool NvDsInferParseCustomSCRFDFixed(
    std::vector<NvDsInferLayerInfo> const& outputLayersInfo,
    NvDsInferNetworkInfo const& networkInfo,
    NvDsInferParseDetectionParams const& detectionParams,
    std::vector<NvDsInferObjectDetectionInfo>& objectList)
{
    const NvDsInferLayerInfo* score8  = findLayer(outputLayersInfo, "448");
    const NvDsInferLayerInfo* bbox8   = findLayer(outputLayersInfo, "451");
    const NvDsInferLayerInfo* kps8    = findLayer(outputLayersInfo, "454");

    const NvDsInferLayerInfo* score16 = findLayer(outputLayersInfo, "471");
    const NvDsInferLayerInfo* bbox16  = findLayer(outputLayersInfo, "474");
    const NvDsInferLayerInfo* kps16   = findLayer(outputLayersInfo, "477");

    const NvDsInferLayerInfo* score32 = findLayer(outputLayersInfo, "494");
    const NvDsInferLayerInfo* bbox32  = findLayer(outputLayersInfo, "497");
    const NvDsInferLayerInfo* kps32   = findLayer(outputLayersInfo, "500");

    if (!score8 || !bbox8 || !kps8 ||
        !score16 || !bbox16 || !kps16 ||
        !score32 || !bbox32 || !kps32) {
        std::cerr << "[SCRFD FIXED PARSER] Missing one or more output layers." << std::endl;
        return false;
    }

    float confThresh = 0.50f;
    if (!detectionParams.perClassPreclusterThreshold.empty()) {
        confThresh = detectionParams.perClassPreclusterThreshold[0];
    }

    // Match config [class-attrs-all] nms-iou-threshold=0.40.
    const float nmsThresh = 0.40f;
    const int topK = 100;

    std::vector<ScrfdDet> dets;
    dets.reserve(512);

    const int netW = static_cast<int>(networkInfo.width);
    const int netH = static_cast<int>(networkInfo.height);

    // SCRFD 640x640:
    // stride 8:  80x80x2 = 12800
    // stride 16: 40x40x2 = 3200
    // stride 32: 20x20x2 = 800
    decodeLevel(
        reinterpret_cast<const float*>(score8->buffer),
        reinterpret_cast<const float*>(bbox8->buffer),
        80, 80, 8, 2, confThresh, netW, netH, dets
    );

    decodeLevel(
        reinterpret_cast<const float*>(score16->buffer),
        reinterpret_cast<const float*>(bbox16->buffer),
        40, 40, 16, 2, confThresh, netW, netH, dets
    );

    decodeLevel(
        reinterpret_cast<const float*>(score32->buffer),
        reinterpret_cast<const float*>(bbox32->buffer),
        20, 20, 32, 2, confThresh, netW, netH, dets
    );

    std::sort(
        dets.begin(),
        dets.end(),
        [](const ScrfdDet& a, const ScrfdDet& b) {
            return a.score > b.score;
        }
    );

    std::vector<ScrfdDet> kept;
    kept.reserve(std::min(static_cast<int>(dets.size()), topK));

    for (const auto& d : dets) {
        bool suppress = false;

        for (const auto& k : kept) {
            if (iou_xyxy(d, k) > nmsThresh) {
                suppress = true;
                break;
            }
        }

        if (!suppress) {
            kept.push_back(d);
            if (static_cast<int>(kept.size()) >= topK) {
                break;
            }
        }
    }

    objectList.clear();

    for (const auto& d : kept) {
        NvDsInferObjectDetectionInfo obj;
        obj.classId = 0;
        obj.detectionConfidence = d.score;
        obj.left = d.x1;
        obj.top = d.y1;
        obj.width = d.x2 - d.x1;
        obj.height = d.y2 - d.y1;
        if (obj.width < SCRFD_MIN_NET_W || obj.height < SCRFD_MIN_NET_H) {
            continue;
        }

        objectList.push_back(obj);
    }

    if (!objectList.empty()) {
        const auto& o = objectList[0];
        std::cerr
            << "[SCRFD FIXED PARSER] objects=" << objectList.size()
            << " top_conf=" << o.detectionConfidence
            << " bbox=[" << o.left << "," << o.top << ","
            << o.width << "," << o.height << "]"
            << std::endl;
    }

    return true;
}

CHECK_CUSTOM_PARSE_FUNC_PROTOTYPE(NvDsInferParseCustomSCRFDFixed);
