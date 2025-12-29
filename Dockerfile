FROM python:3.13.7-slim

ENV PYTHONDONTWRITECODE=1
ENV PYTHONUNBUFFERED=1

ADD requirements.txt /app

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY . /app

EXPOSE 8000

CMD [uvicorn app.main:app --host 0.0.0.0 --port 8000]