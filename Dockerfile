FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 9090
CMD ["python", "-m", "uvicorn", "paymock.main:app", "--host", "0.0.0.0", "--port", "9090"]
