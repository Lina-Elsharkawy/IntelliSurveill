import cv2
import ollama
import time

# ============================================================
# CONFIG
# ============================================================
IMAGE_PATH  = r"E:\AI-Edge\Graduation-Project\datasets\anomaly_test\Fight1\frames\win_21.jpg"   # ← change this
OLLAMA_HOST = "http://localhost:11435"
VLM_MODEL   = "openbmb/minicpm-v4.5:8b"

# ============================================================
# Load Image
# ============================================================
def load_image(image_path):
    img = cv2.imread(image_path)

    if img is None:
        print("❌ Failed to load image")
        return []

    # resize for performance (important for your GPU)
    img = cv2.resize(img, (512, 512))

    # encode to jpg bytes
    _, buf = cv2.imencode(
        ".jpg",
        img,
        [cv2.IMWRITE_JPEG_QUALITY, 85]
    )

    print("✅ Image loaded")
    print(f"📦 Size: {len(buf.tobytes())/1024:.1f} KB")

    return [buf.tobytes()]   # MUST be a list

# ============================================================
# Run VLM
# ============================================================
def run_vlm(client, images):
    print(f"\n🔍 Sending {len(images)} image(s) to {VLM_MODEL}...")
    t0 = time.time()

    response = client.generate(
        model = VLM_MODEL,
        prompt = (
            "You are a surveillance analyst reviewing security camera footage. "
            "Look carefully at this image and describe: "
            "1. How many people are visible and where are they located? "
            "2. What is each person doing with their hands and body? "
            "3. Is anyone touching, taking, or interfering with objects or property? "
            "4. Is there any suspicious, aggressive, or unusual behavior? "
            "5. Any weapons, stolen items, or dangerous objects visible? "
            "Be very specific and detailed. Describe exactly what you see."
        ),
        images = images,
        stream = False,
        options = {
            "temperature": 0.1,
            "top_p": 0.9,
            "repeat_penalty": 1.1,

            # 🔥 VERY IMPORTANT for your GPU
            "num_predict": 512,
            "num_ctx": 512
        }
    )

    result  = (response.get("response") or "").strip()
    elapsed = round(time.time() - t0, 2)

    print(f"\n{'='*55}")
    print(f"📝 RESULT ({elapsed}s):")
    print(f"{'='*55}")
    print(result)
    print(f"{'='*55}")

    return result

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    client = ollama.Client(host=OLLAMA_HOST)

    try:
        client.list()
        print("✅ Ollama reachable")
    except Exception as e:
        print(f"❌ Cannot reach Ollama: {e}")
        exit(1)

    images = load_image(IMAGE_PATH)

    if not images:
        print("❌ No image to process")
        exit(1)

    run_vlm(client, images)