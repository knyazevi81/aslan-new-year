FROM python:3.13.7-slim

ENV PYTHONDONTWRITECODE=1
ENV PYTHONUNBUFFERED=1

ADD requirements.txt /app

RUN pip install --upgrade pip
RUN pip install fastapi uvicorn[standard] jinja2 pydantic python-multipart itsdangerous reportlab pytest httpx ruff black

COPY . /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]