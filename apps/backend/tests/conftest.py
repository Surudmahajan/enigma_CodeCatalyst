import os

# Configure the test environment before the app is imported.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./var/test.db"
os.environ["JOBS_MODE"] = "eager"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["STORAGE_LOCAL_DIR"] = "./var/test-storage"
os.environ["AI_PROVIDER"] = "none"
os.environ["PUSH_PROVIDER"] = "none"
os.environ["JWT_SECRET"] = "test-access-secret-at-least-32-bytes-long-xx"
os.environ["JWT_REFRESH_SECRET"] = "test-refresh-secret-at-least-32-bytes-long-x"
