# Containerised batch job for a Bayesian MMM fit.
#
# Runs as a batch Job (not a long-lived service): the container does one fit and
# exits. ENTRYPOINT (not CMD) is used so scheduler-supplied flags append after
# `python -u main.py` - e.g. a scheduler can invoke the same image with
# `--kpi revenue` or `--window h1` without rebuilding.
FROM python:3.12-slim

WORKDIR /app

# System deps some scientific wheels expect.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# `-u` for unbuffered logs so a batch runner streams progress live.
ENTRYPOINT ["python", "-u", "main.py"]
# Default args if none are supplied; a scheduler appends its own flags.
CMD ["--kpi", "revenue"]
