FROM filegrid-backend:0.1.0

USER root
COPY backend/requirements-test.txt backend/requirements.txt /tmp/test-dependencies/
RUN pip install --no-cache-dir -q -r /tmp/test-dependencies/requirements-test.txt
COPY backend/tests /app/backend/tests
COPY backend/pytest.ini /app/backend/pytest.ini
COPY scripts /app/scripts
COPY model-ML/filegrid-history-v2 /app/model-ML/filegrid-history-v2
COPY model-ML/filegrid-model-handoff/examples /app/model-ML/filegrid-model-handoff/examples
USER 10001:10001

CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
