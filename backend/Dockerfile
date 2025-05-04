FROM python:3.10-slim

# 1. Install OS packages needed to build EVERYTHING
RUN apt-get update -o Acquire::ForceIPv4=true \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential \
      python3-dev \
      cmake \
      rustc \
      cargo \
      ffmpeg \
      libsndfile1 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copy & install Python deps
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# 3. Copy our app
COPY . /app

# 4. Runtime command
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]