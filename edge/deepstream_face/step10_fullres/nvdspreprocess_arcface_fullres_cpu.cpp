
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <string>
#include <unordered_map>

#include <gst/gst.h>
#include <cuda_runtime.h>

#include "nvdspreprocess_lib.h"
#include "nvdspreprocess_interface.h"
#include "gstnvdsmeta.h"
#include "gstnvdsinfer.h"
#include "nvbufsurface.h"

struct CustomCtx
{
    CustomInitParams initParams;
    int printed = 0;
};

struct FaceDecoded
{
    bool ok = false;
    float score = 0.0f;
    float kps[5][2];
    float bbox[4];
};

static const float ARC_DST[5][2] = {
    {38.2946f, 51.6963f},
    {73.5318f, 51.5014f},
    {56.0252f, 71.7366f},
    {41.5493f, 92.3655f},
    {70.7299f, 92.2041f}
};

extern "C"
CustomCtx *initLib(CustomInitParams initparams)
{
    CustomCtx *ctx = new CustomCtx;
    ctx->initParams = initparams;

    printf("[ArcFaceFullResCPU] initLib unique_id=%u\n", initparams.unique_id);
    printf("[ArcFaceFullResCPU] tensor_name=%s\n", initparams.tensor_params.tensor_name.c_str());
    printf("[ArcFaceFullResCPU] buffer_size=%lu\n", (unsigned long)initparams.tensor_params.buffer_size);

    return ctx;
}

extern "C"
void deInitLib(CustomCtx *ctx)
{
    printf("[ArcFaceFullResCPU] deInitLib\n");
    delete ctx;
}

extern "C"
NvDsPreProcessStatus CustomTransformation(
    NvBufSurface *in_surf,
    NvBufSurface *out_surf,
    CustomTransformParams &params)
{
    // Step 10A:
    // We do not depend on converted_frame_ptr. Tensor preparation maps the
    // original full-resolution NvBufSurface safely through batch->inbuf.
    return NVDSPREPROCESS_SUCCESS;
}

extern "C"
NvDsPreProcessStatus CustomAsyncTransformation(
    NvBufSurface *in_surf,
    NvBufSurface *out_surf,
    CustomTransformParams &params)
{
    return CustomTransformation(in_surf, out_surf, params);
}

static int layer_num_elements(const NvDsInferLayerInfo &layer)
{
    int count = 1;
    for (int i = 0; i < layer.inferDims.numDims; ++i) {
        count *= layer.inferDims.d[i];
    }
    return count;
}

static int find_layer_index(NvDsInferTensorMeta *tensor_meta, const char *name)
{
    if (!tensor_meta) return -1;

    for (unsigned int i = 0; i < tensor_meta->num_output_layers; ++i) {
        NvDsInferLayerInfo &layer = tensor_meta->output_layers_info[i];

        if (layer.layerName && strcmp(layer.layerName, name) == 0) {
            return (int)i;
        }
    }

    return -1;
}

static NvDsInferTensorMeta *find_scrfd_tensor_meta(NvDsBatchMeta *batch_meta)
{
    if (!batch_meta) return nullptr;

    NvDsMetaList *l_frame = batch_meta->frame_meta_list;

    while (l_frame) {
        NvDsFrameMeta *frame_meta = (NvDsFrameMeta *)l_frame->data;

        NvDsMetaList *l_user = frame_meta->frame_user_meta_list;
        while (l_user) {
            NvDsUserMeta *user_meta = (NvDsUserMeta *)l_user->data;

            if (user_meta &&
                user_meta->base_meta.meta_type == NVDSINFER_TENSOR_OUTPUT_META) {

                NvDsInferTensorMeta *tensor_meta =
                    (NvDsInferTensorMeta *)user_meta->user_meta_data;

                if (tensor_meta && tensor_meta->unique_id == 1) {
                    return tensor_meta;
                }
            }

            l_user = l_user->next;
        }

        l_frame = l_frame->next;
    }

    return nullptr;
}

static FaceDecoded decode_best_scrfd(NvDsInferTensorMeta *tensor_meta)
{
    FaceDecoded out;

    if (!tensor_meta) return out;

    const char *score_names[3] = {"448", "471", "494"};
    const char *bbox_names[3]  = {"451", "474", "497"};
    const char *kps_names[3]   = {"454", "477", "500"};

    const int feat_w[3] = {80, 40, 20};
    const int stride[3] = {8, 16, 32};

    float best_score = -1.0f;
    int best_level = -1;
    int best_idx = -1;

    for (int level = 0; level < 3; ++level) {
        int sidx = find_layer_index(tensor_meta, score_names[level]);
        if (sidx < 0) continue;

        float *scores = (float *)(tensor_meta->out_buf_ptrs_host ?
                                  tensor_meta->out_buf_ptrs_host[sidx] : nullptr);

        if (!scores) continue;

        int count = layer_num_elements(tensor_meta->output_layers_info[sidx]);

        for (int i = 0; i < count; ++i) {
            if (scores[i] > best_score) {
                best_score = scores[i];
                best_level = level;
                best_idx = i;
            }
        }
    }

    if (best_level < 0 || best_idx < 0) return out;

    int bidx = find_layer_index(tensor_meta, bbox_names[best_level]);
    int kidx = find_layer_index(tensor_meta, kps_names[best_level]);

    if (bidx < 0 || kidx < 0) return out;

    float *bbox = (float *)tensor_meta->out_buf_ptrs_host[bidx];
    float *kps  = (float *)tensor_meta->out_buf_ptrs_host[kidx];

    if (!bbox || !kps) return out;

    int st = stride[best_level];
    int fw = feat_w[best_level];

    int anchor_pair_index = best_idx / 2;
    int y = anchor_pair_index / fw;
    int x = anchor_pair_index % fw;

    float cx = ((float)x + 0.5f) * (float)st;
    float cy = ((float)y + 0.5f) * (float)st;

    float *b = bbox + best_idx * 4;

    out.bbox[0] = cx - b[0] * st;
    out.bbox[1] = cy - b[1] * st;
    out.bbox[2] = cx + b[2] * st;
    out.bbox[3] = cy + b[3] * st;

    float *kp = kps + best_idx * 10;

    for (int j = 0; j < 5; ++j) {
        out.kps[j][0] = cx + kp[2*j] * st;
        out.kps[j][1] = cy + kp[2*j + 1] * st;
    }

    out.score = best_score;
    out.ok = true;

    return out;
}

static void compute_5pt_similarity_dst_to_src(
    const FaceDecoded &face,
    float src_w,
    float src_h,
    float &a00,
    float &a01,
    float &a02,
    float &a10,
    float &a11,
    float &a12)
{
    float src_pts[5][2];

    // SCRFD tensor is 640x640. Map to original frame dimensions.
    float scale_x = src_w / 640.0f;
    float scale_y = src_h / 640.0f;

    for (int i = 0; i < 5; ++i) {
        src_pts[i][0] = face.kps[i][0] * scale_x;
        src_pts[i][1] = face.kps[i][1] * scale_y;
    }

    float mdx = 0.0f, mdy = 0.0f;
    float msx = 0.0f, msy = 0.0f;

    for (int i = 0; i < 5; ++i) {
        mdx += ARC_DST[i][0];
        mdy += ARC_DST[i][1];
        msx += src_pts[i][0];
        msy += src_pts[i][1];
    }

    mdx /= 5.0f;
    mdy /= 5.0f;
    msx /= 5.0f;
    msy /= 5.0f;

    float den = 0.0f;
    float num_a = 0.0f;
    float num_b = 0.0f;

    for (int i = 0; i < 5; ++i) {
        float dx = ARC_DST[i][0] - mdx;
        float dy = ARC_DST[i][1] - mdy;

        float sx = src_pts[i][0] - msx;
        float sy = src_pts[i][1] - msy;

        den += dx * dx + dy * dy;

        // src = [a -b; b a] * dst + t
        num_a += dx * sx + dy * sy;
        num_b += dx * sy - dy * sx;
    }

    if (den < 1e-6f) {
        a00 = 1.0f; a01 = 0.0f; a02 = 0.0f;
        a10 = 0.0f; a11 = 1.0f; a12 = 0.0f;
        return;
    }

    float a = num_a / den;
    float b = num_b / den;

    a00 = a;
    a01 = -b;
    a02 = msx - a * mdx + b * mdy;

    a10 = b;
    a11 = a;
    a12 = msy - b * mdx - a * mdy;
}

static inline float clampf(float v, float lo, float hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

static inline unsigned char sample_plane_nearest(
    const unsigned char *base,
    int pitch,
    int w,
    int h,
    int x,
    int y)
{
    x = (int)clampf((float)x, 0.0f, (float)(w - 1));
    y = (int)clampf((float)y, 0.0f, (float)(h - 1));
    return base[y * pitch + x];
}

static void nv12_to_aligned_tensor_cpu(
    const unsigned char *y_plane,
    const unsigned char *uv_plane,
    int src_w,
    int src_h,
    int y_pitch,
    int uv_pitch,
    float *dst,
    float a00,
    float a01,
    float a02,
    float a10,
    float a11,
    float a12)
{
    const int W = 112;
    const int H = 112;
    const int total = W * H;

    for (int oy = 0; oy < H; ++oy) {
        for (int ox = 0; ox < W; ++ox) {
            int idx = oy * W + ox;

            float sx = a00 * (float)ox + a01 * (float)oy + a02;
            float sy = a10 * (float)ox + a11 * (float)oy + a12;

            int ix = (int)(sx + 0.5f);
            int iy = (int)(sy + 0.5f);

            float r = 0.0f, g = 0.0f, b = 0.0f;

            if (ix >= 0 && ix < src_w && iy >= 0 && iy < src_h) {
                unsigned char Yv = sample_plane_nearest(y_plane, y_pitch, src_w, src_h, ix, iy);

                int uv_x = ix & ~1;
                int uv_y = iy / 2;

                if (uv_x < 0) uv_x = 0;
                if (uv_x + 1 >= src_w) uv_x = src_w - 2;
                if (uv_y < 0) uv_y = 0;
                if (uv_y >= src_h / 2) uv_y = src_h / 2 - 1;

                const unsigned char *uvp = uv_plane + uv_y * uv_pitch + uv_x;

                float Y = (float)Yv;
                float U = (float)uvp[0] - 128.0f;
                float V = (float)uvp[1] - 128.0f;

                r = Y + 1.402f * V;
                g = Y - 0.344136f * U - 0.714136f * V;
                b = Y + 1.772f * U;

                r = clampf(r, 0.0f, 255.0f);
                g = clampf(g, 0.0f, 255.0f);
                b = clampf(b, 0.0f, 255.0f);
            }

            dst[0 * total + idx] = (r - 127.5f) / 128.0f;
            dst[1 * total + idx] = (g - 127.5f) / 128.0f;
            dst[2 * total + idx] = (b - 127.5f) / 128.0f;
        }
    }
}

extern "C"
NvDsPreProcessStatus CustomTensorPreparation(
    CustomCtx *ctx,
    NvDsPreProcessBatch *batch,
    NvDsPreProcessCustomBuf *&buf,
    CustomTensorParams &tensorParam,
    NvDsPreProcessAcquirer *acquirer)
{
    if (!ctx || !batch || batch->units.empty()) {
        printf("[ArcFaceFullResCPU] ERROR: invalid ctx/batch\n");
        return NVDSPREPROCESS_INVALID_PARAMS;
    }

    NvDsPreProcessUnit &unit = batch->units[0];

    NvDsInferTensorMeta *scrfd_tensor = find_scrfd_tensor_meta(batch->batch_meta);
    FaceDecoded face = decode_best_scrfd(scrfd_tensor);

    buf = acquirer->acquire();

    if (!buf || !buf->memory_ptr) {
        printf("[ArcFaceFullResCPU] ERROR: failed to acquire tensor buffer\n");
        return NVDSPREPROCESS_RESOURCE_ERROR;
    }

    const int batch_size = (int)batch->units.size();
    const int total = batch_size * 3 * 112 * 112;
    const unsigned long required_bytes = (unsigned long)total * sizeof(float);

    if (required_bytes > tensorParam.params.buffer_size) {
        printf("[ArcFaceFullResCPU] ERROR: required_bytes=%lu > buffer_size=%lu\n",
               required_bytes,
               (unsigned long)tensorParam.params.buffer_size);
        return NVDSPREPROCESS_CONFIG_FAILED;
    }

    std::vector<float> host_tensor(total, 0.0f);

    if (!face.ok) {
        printf("[ArcFaceFullResCPU] WARN: no SCRFD face decoded; emitting zero tensor\n");
    } else if (!batch->inbuf) {
        printf("[ArcFaceFullResCPU] ERROR: batch->inbuf is NULL; emitting zero tensor\n");
    } else {
        GstMapInfo map_info;
        memset(&map_info, 0, sizeof(map_info));

        if (!gst_buffer_map(batch->inbuf, &map_info, GST_MAP_READ)) {
            printf("[ArcFaceFullResCPU] ERROR: gst_buffer_map failed; emitting zero tensor\n");
        } else {
            NvBufSurface *surf = (NvBufSurface *)map_info.data;
            guint idx = unit.batch_index;

            if (!surf || !surf->surfaceList || idx >= surf->batchSize) {
                printf("[ArcFaceFullResCPU] ERROR: invalid NvBufSurface/batch index; emitting zero tensor\n");
            } else {
                int map_ret = NvBufSurfaceMap(surf, idx, -1, NVBUF_MAP_READ);
                int sync_ret = -1;

                if (map_ret == 0) {
                    sync_ret = NvBufSurfaceSyncForCpu(surf, idx, -1);
                }

                if (map_ret != 0 || sync_ret != 0) {
                    printf("[ArcFaceFullResCPU] ERROR: NvBufSurfaceMap/SyncForCpu failed map=%d sync=%d; emitting zero tensor\n",
                           map_ret, sync_ret);
                } else {
                    NvBufSurfaceParams &sp = surf->surfaceList[idx];

                    int src_w = (int)sp.width;
                    int src_h = (int)sp.height;

                    int y_pitch = (int)sp.planeParams.pitch[0];
                    int uv_pitch = (int)sp.planeParams.pitch[1];

                    if (src_w <= 0) src_w = 640;
                    if (src_h <= 0) src_h = 480;
                    if (y_pitch <= 0) y_pitch = (int)sp.pitch;
                    if (y_pitch <= 0) y_pitch = src_w;
                    if (uv_pitch <= 0) uv_pitch = y_pitch;

                    unsigned char *y_plane = (unsigned char *)sp.mappedAddr.addr[0];
                    unsigned char *uv_plane = (unsigned char *)sp.mappedAddr.addr[1];

                    if (!y_plane) {
                        printf("[ArcFaceFullResCPU] ERROR: mapped Y plane is NULL; emitting zero tensor\n");
                    } else {
                        if (!uv_plane) {
                            uv_plane = y_plane + y_pitch * src_h;
                        }

                        float a00, a01, a02, a10, a11, a12;

                        compute_5pt_similarity_dst_to_src(
                            face,
                            (float)src_w,
                            (float)src_h,
                            a00, a01, a02,
                            a10, a11, a12);

                        nv12_to_aligned_tensor_cpu(
                            y_plane,
                            uv_plane,
                            src_w,
                            src_h,
                            y_pitch,
                            uv_pitch,
                            host_tensor.data(),
                            a00, a01, a02,
                            a10, a11, a12);

                        if (ctx->printed < 30) {
                            printf("[ArcFaceFullResCPU] prepared FULLRES aligned tensor score=%f src=%dx%d y_pitch=%d uv_pitch=%d colorFormat=%d\n",
                                   face.score,
                                   src_w,
                                   src_h,
                                   y_pitch,
                                   uv_pitch,
                                   (int)sp.colorFormat);

                            printf("[ArcFaceFullResCPU] kps_net=[%.2f,%.2f],[%.2f,%.2f],[%.2f,%.2f],[%.2f,%.2f],[%.2f,%.2f]\n",
                                   face.kps[0][0], face.kps[0][1],
                                   face.kps[1][0], face.kps[1][1],
                                   face.kps[2][0], face.kps[2][1],
                                   face.kps[3][0], face.kps[3][1],
                                   face.kps[4][0], face.kps[4][1]);

                            ctx->printed++;
                        }
                    }

                    NvBufSurfaceUnMap(surf, idx, -1);
                }
            }

            gst_buffer_unmap(batch->inbuf, &map_info);
        }
    }

    cudaError_t cerr = cudaMemcpy(
        buf->memory_ptr,
        host_tensor.data(),
        required_bytes,
        cudaMemcpyHostToDevice);

    if (cerr != cudaSuccess) {
        printf("[ArcFaceFullResCPU] ERROR: cudaMemcpy HostToDevice failed: %s\n",
               cudaGetErrorString(cerr));
        return NVDSPREPROCESS_CUDA_ERROR;
    }

    tensorParam.params.network_input_shape[0] = batch_size;

    return NVDSPREPROCESS_SUCCESS;
}
