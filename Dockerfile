# Lichte Python-versie die werkt op de Raspberry Pi (ARM) en op een gewone pc
FROM python:3.11-slim

# Werkmap in de container
WORKDIR /app

# Eerst de bibliotheken, zodat die laag gecachet blijft bij codewijzigingen
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Daarna de applicatie zelf
COPY . .

# Start de bot (-u: logregels direct zichtbaar in `docker compose logs`)
CMD ["python", "-u", "bot.py"]
