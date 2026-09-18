FROM python:3.11-slim

# تثبيت FFmpeg وDeno المطلوبين لـ yt-dlp مع YouTube الحديث
RUN apt-get update && apt-get install -y ffmpeg git curl unzip \
	&& curl -fsSL https://deno.land/install.sh | sh \
	&& ln -s /root/.deno/bin/deno /usr/local/bin/deno \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
COPY music_api/requirements.txt music_api/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r music_api/requirements.txt

COPY . .

CMD ["python", "bot.py"]