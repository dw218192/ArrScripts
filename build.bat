@echo off
pushd %~dp0

SET PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring

poetry lock
poetry install

popd