# TruthLens on a Hugging Face Space (Docker SDK, CPU). Always-on backup for the GPU laptop deployment.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libsndfile1 curl \
 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r /app/backend/requirements.txt

ENV HF_HOME=/app/hf \
    TRUTHLENS_DATA=/tmp/truthlens/cases \
    TRUTHLENS_WHISPER=base \
    DFDC_WEIGHTS=/app/models/dfdc \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=2

# Bake the benchmarked detectors into the image so a cold start doesn't re-download ~3 GB.
RUN python -c "from huggingface_hub import snapshot_download as s; \
[s(r) for r in ['buildborderless/CommunityForensics-DeepfakeDet-ViT','haywoodsloan/ai-image-detector-deploy', \
'umm-maybe/AI-image-detector','mo-thecreator/Deepfake-audio-detection', \
'Gustking/wav2vec2-large-xlsr-deepfake-audio-classification','Systran/faster-whisper-base']]"
RUN mkdir -p /app/models/dfdc && curl -sSL --retry 3 -o /app/models/dfdc/final_999_DeepFakeClassifier_tf_efficientnet_b7_ns_0_23 \
    https://github.com/selimsef/dfdc_deepfake_challenge/releases/download/0.0.1/final_999_DeepFakeClassifier_tf_efficientnet_b7_ns_0_23

COPY --chown=user . /app
RUN chown -R user /app
USER user
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--app-dir", "/app/backend"]
