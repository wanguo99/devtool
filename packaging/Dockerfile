# The full image includes binutils. All Python build dependencies are staged
# by the caller and installed offline to avoid slow in-container downloads.
FROM python:3.11-bullseye@sha256:df0bd610af061603b29d63eb82027b64d5a3f15506e39270422b10b2a55079fc
COPY requirements.txt /tmp/devtool-build-requirements.txt
COPY wheels /tmp/devtool-build-wheels
RUN python -m pip install --no-index --find-links /tmp/devtool-build-wheels -r /tmp/devtool-build-requirements.txt
