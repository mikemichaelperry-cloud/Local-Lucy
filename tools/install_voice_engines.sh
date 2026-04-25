#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
WORKSPACE_ROOT="$(dirname -- "$(dirname -- "${ROOT}")")"
UI_ROOT="${LUCY_UI_ROOT:-${WORKSPACE_ROOT}/ui-v7}"
UI_VENV_PY="${UI_ROOT}/.venv/bin/python3"
UI_TTS_REQUIREMENTS_FILE="${LUCY_UI_VOICE_TTS_REQUIREMENTS_FILE:-${UI_ROOT}/tools/voice_tts_requirements.txt}"

INSTALL_PREFIX_RAW="${LUCY_VOICE_INSTALL_PREFIX:-runtime/voice}"
LUCY_VOICE_MODEL="${LUCY_VOICE_MODEL:-small.en}"
LUCY_VOICE_PIPER_VOICE="${LUCY_VOICE_PIPER_VOICE:-en_GB-cori-high}"

if [[ "${INSTALL_PREFIX_RAW}" = /* ]]; then
  INSTALL_PREFIX="${INSTALL_PREFIX_RAW}"
else
  INSTALL_PREFIX="${ROOT}/${INSTALL_PREFIX_RAW}"
fi

RUNTIME_DIR="${INSTALL_PREFIX}"
BIN_DIR="${RUNTIME_DIR}/bin"
MODEL_DIR="${RUNTIME_DIR}/models"
WHISPER_REPO="${RUNTIME_DIR}/whisper.cpp"
WHISPER_MODEL_PATH="${MODEL_DIR}/ggml-${LUCY_VOICE_MODEL}.bin"

PIPER_DIR="${MODEL_DIR}/piper/${LUCY_VOICE_PIPER_VOICE}"
PIPER_MODEL_PATH="${PIPER_DIR}/${LUCY_VOICE_PIPER_VOICE}.onnx"
PIPER_MODEL_JSON_PATH="${PIPER_DIR}/${LUCY_VOICE_PIPER_VOICE}.onnx.json"

WHISPER_REPO_URL="${LUCY_VOICE_WHISPER_REPO_URL:-https://github.com/ggerganov/whisper.cpp.git}"
WHISPER_MODEL_URL="${LUCY_VOICE_WHISPER_MODEL_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${LUCY_VOICE_MODEL}.bin}"
PIPER_URL="${LUCY_VOICE_PIPER_URL:-https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz}"
PIPER_VOICE_ONNX_URL="${LUCY_VOICE_PIPER_VOICE_ONNX_URL:-https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/high/en_GB-cori-high.onnx}"
PIPER_VOICE_JSON_URL="${LUCY_VOICE_PIPER_VOICE_JSON_URL:-https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/high/en_GB-cori-high.onnx.json}"
PIPER_PY_PACKAGE="${LUCY_VOICE_PIPER_PY_PACKAGE:-piper-tts==1.4.1}"
PIPER_PY_EXTRA_PACKAGES="${LUCY_VOICE_PIPER_PY_EXTRA_PACKAGES:-pathvalidate}"
PIPER_INSTALL_MODE="${LUCY_VOICE_PIPER_INSTALL_MODE:-python}"
PIPER_VENV_DIR="${RUNTIME_DIR}/piper-venv"
PIPER_VENV_BIN="${PIPER_VENV_DIR}/bin/piper"

SKIP_APT="${LUCY_VOICE_INSTALL_SKIP_APT:-0}"

say(){ echo "$*"; }
warn(){ echo "WARN: $*" >&2; }
die(){ echo "ERROR: $*" >&2; exit 1; }

require_cmd(){
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

download_file(){
  local url="$1"
  local out="$2"
  mkdir -p "$(dirname "${out}")"
  rm -f "${out}" >/dev/null 2>&1 || true

  if command -v curl >/dev/null 2>&1; then
    if curl -fL --retry 2 -o "${out}" "${url}" >/dev/null 2>&1; then
      return 0
    fi
  fi

  if command -v wget >/dev/null 2>&1; then
    if wget -O "${out}" "${url}" >/dev/null 2>&1; then
      return 0
    fi
  fi

  return 1
}

apt_run(){
  if [[ "${SKIP_APT}" == "1" ]]; then
    say "INFO: skipping apt install (LUCY_VOICE_INSTALL_SKIP_APT=1)"
    return 0
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    warn "apt-get not found; skipping package install"
    return 0
  fi

  local -a apt_cmd
  if [[ "$(id -u)" -eq 0 ]]; then
    apt_cmd=(apt-get)
  else
    if command -v sudo >/dev/null 2>&1; then
      apt_cmd=(sudo apt-get)
    else
      die "need root/sudo for apt-get, or set LUCY_VOICE_INSTALL_SKIP_APT=1"
    fi
  fi

  say "INFO: installing system packages"
  "${apt_cmd[@]}" update
  "${apt_cmd[@]}" install -y build-essential cmake ffmpeg git alsa-utils sox
}

detect_os(){
  local name="unknown"
  if [[ -f /etc/os-release ]]; then
    name="$(. /etc/os-release; echo "${ID:-unknown}")"
  fi
  say "INFO: detected OS: ${name}"
  if [[ "${name}" != "ubuntu" && "${name}" != "debian" ]]; then
    warn "this installer is tuned for Ubuntu/Debian"
  fi
}

install_whisper(){
  require_cmd git
  require_cmd cmake

  mkdir -p "${RUNTIME_DIR}" "${BIN_DIR}" "${MODEL_DIR}"

  if [[ -d "${WHISPER_REPO}/.git" ]]; then
    say "INFO: whisper.cpp already present; updating"
    git -C "${WHISPER_REPO}" pull --ff-only >/dev/null 2>&1 || warn "whisper.cpp update skipped"
  else
    say "INFO: cloning whisper.cpp"
    git clone --depth 1 "${WHISPER_REPO_URL}" "${WHISPER_REPO}"
  fi

  say "INFO: building whisper.cpp"
  cmake -S "${WHISPER_REPO}" -B "${WHISPER_REPO}/build"
  cmake --build "${WHISPER_REPO}/build" -j

  local src=""
  for cand in \
    "${WHISPER_REPO}/build/bin/whisper-cli" \
    "${WHISPER_REPO}/build/bin/whisper" \
    "${WHISPER_REPO}/build/bin/main"; do
    if [[ -x "${cand}" ]]; then
      src="${cand}"
      break
    fi
  done

  [[ -n "${src}" ]] || die "whisper build succeeded but binary not found"

  cp -f "${src}" "${BIN_DIR}/whisper"
  chmod +x "${BIN_DIR}/whisper"
  say "OK: whisper binary installed at ${BIN_DIR}/whisper"
}

download_whisper_model(){
  if [[ -s "${WHISPER_MODEL_PATH}" ]]; then
    say "INFO: whisper model already present: ${WHISPER_MODEL_PATH}"
    return 0
  fi

  say "INFO: downloading whisper model ${LUCY_VOICE_MODEL}"
  download_file "${WHISPER_MODEL_URL}" "${WHISPER_MODEL_PATH}" || die "failed to download whisper model"
  [[ -s "${WHISPER_MODEL_PATH}" ]] || die "whisper model download produced empty file"
  say "OK: whisper model installed at ${WHISPER_MODEL_PATH}"
}

link_piper_bin(){
  mkdir -p "${BIN_DIR}"
  ln -sfn "../piper-venv/bin/piper" "${BIN_DIR}/piper"
  [[ -x "${BIN_DIR}/piper" ]]
}

install_piper_python(){
  mkdir -p "${RUNTIME_DIR}" "${BIN_DIR}" "${PIPER_DIR}"

  if ! command -v python3 >/dev/null 2>&1; then
    warn "python3 not found; cannot install piper-tts package"
    return 1
  fi

  if [[ -x "${PIPER_VENV_BIN}" ]]; then
    if "${PIPER_VENV_BIN}" --help >/dev/null 2>&1 && link_piper_bin; then
      say "INFO: piper-tts already present in ${PIPER_VENV_DIR}"
      return 0
    fi
    warn "existing piper-tts environment is unhealthy; repairing"
  fi

  say "INFO: installing piper-tts package (${PIPER_PY_PACKAGE})"
  python3 -m venv "${PIPER_VENV_DIR}" || {
    warn "failed creating piper virtualenv at ${PIPER_VENV_DIR}"
    return 1
  }

  if ! "${PIPER_VENV_DIR}/bin/python" -m pip install --upgrade pip >/dev/null 2>&1; then
    warn "pip self-upgrade failed in ${PIPER_VENV_DIR}"
  fi

  if ! "${PIPER_VENV_DIR}/bin/python" -m pip install --upgrade "${PIPER_PY_PACKAGE}" >/dev/null 2>&1; then
    warn "piper-tts install failed (${PIPER_PY_PACKAGE})"
    return 1
  fi
  if [[ -n "${PIPER_PY_EXTRA_PACKAGES}" ]]; then
    if ! "${PIPER_VENV_DIR}/bin/python" -m pip install --upgrade ${PIPER_PY_EXTRA_PACKAGES} >/dev/null 2>&1; then
      warn "piper extra python deps install failed (${PIPER_PY_EXTRA_PACKAGES})"
      return 1
    fi
  fi

  if [[ ! -x "${PIPER_VENV_BIN}" ]]; then
    warn "piper executable missing after piper-tts install"
    return 1
  fi

  link_piper_bin || {
    warn "failed linking runtime piper binary"
    return 1
  }

  say "OK: piper installed from python package at ${PIPER_VENV_BIN}"
  return 0
}

install_piper_legacy(){
  mkdir -p "${BIN_DIR}" "${PIPER_DIR}"

  if [[ -L "${BIN_DIR}/piper" ]]; then
    rm -f "${BIN_DIR}/piper" >/dev/null 2>&1 || true
  fi

  if [[ -x "${BIN_DIR}/piper" ]]; then
    if [[ -s "${BIN_DIR}/libpiper_phonemize.so.1" && -s "${BIN_DIR}/libonnxruntime.so.1.14.1" ]]; then
      say "INFO: legacy piper runtime already present: ${BIN_DIR}/piper"
      return 0
    fi
    say "INFO: piper binary present but legacy runtime libs missing; reinstalling bundled runtime"
  fi

  local tmpd archive extracted piper_src piper_root
  tmpd="$(mktemp -d)"
  archive="${tmpd}/piper.tar.gz"
  extracted="${tmpd}/extract"
  mkdir -p "${extracted}"

  if ! download_file "${PIPER_URL}" "${archive}"; then
    rm -rf "${tmpd}" >/dev/null 2>&1 || true
    warn "piper download failed"
    return 1
  fi

  if ! tar -xzf "${archive}" -C "${extracted}"; then
    rm -rf "${tmpd}" >/dev/null 2>&1 || true
    warn "piper extract failed"
    return 1
  fi

  piper_src="$(find "${extracted}" -type f -name piper | head -n 1 || true)"
  if [[ -z "${piper_src}" ]]; then
    rm -rf "${tmpd}" >/dev/null 2>&1 || true
    warn "piper binary not found in archive"
    return 1
  fi
  piper_root="$(dirname "${piper_src}")"

  cp -f "${piper_src}" "${BIN_DIR}/piper"
  chmod +x "${BIN_DIR}/piper"

  # Piper needs bundled runtime libs at runtime (binary RUNPATH is $ORIGIN).
  # Copy available shared libs and supporting data from the release archive.
  cp -a "${piper_root}"/lib*.so* "${BIN_DIR}/" 2>/dev/null || true
  if [[ -f "${piper_root}/libtashkeel_model.ort" ]]; then
    cp -f "${piper_root}/libtashkeel_model.ort" "${BIN_DIR}/libtashkeel_model.ort"
  fi
  if [[ -f "${piper_root}/piper_phonemize" ]]; then
    cp -f "${piper_root}/piper_phonemize" "${BIN_DIR}/piper_phonemize"
    chmod +x "${BIN_DIR}/piper_phonemize"
  fi
  while IFS= read -r -d '' support_dir; do
    rm -rf "${BIN_DIR}/$(basename "${support_dir}")" >/dev/null 2>&1 || true
    cp -a "${support_dir}" "${BIN_DIR}/$(basename "${support_dir}")"
  done < <(find "${piper_root}" -mindepth 1 -maxdepth 1 -type d -print0)

  rm -rf "${tmpd}" >/dev/null 2>&1 || true
  say "OK: piper binary installed at ${BIN_DIR}/piper"
  return 0
}

install_piper(){
  case "${PIPER_INSTALL_MODE}" in
    python)
      if install_piper_python; then
        return 0
      fi
      warn "python piper install failed; trying legacy piper tarball"
      install_piper_legacy
      return $?
      ;;
    legacy)
      install_piper_legacy
      return $?
      ;;
    auto)
      if install_piper_python; then
        return 0
      fi
      warn "python piper install failed; trying legacy piper tarball"
      install_piper_legacy
      return $?
      ;;
    *)
      warn "unknown LUCY_VOICE_PIPER_INSTALL_MODE=${PIPER_INSTALL_MODE}; using auto"
      if install_piper_python; then
        return 0
      fi
      install_piper_legacy
      return $?
      ;;
  esac
}

install_ui_v7_kokoro(){
  if [[ ! -x "${UI_VENV_PY}" ]]; then
    warn "ui-v7 python not found at ${UI_VENV_PY}; skipping kokoro install"
    return 1
  fi
  if [[ ! -f "${UI_TTS_REQUIREMENTS_FILE}" ]]; then
    warn "ui-v7 TTS requirements file missing: ${UI_TTS_REQUIREMENTS_FILE}"
    return 1
  fi

  say "INFO: installing ui-v7 Kokoro/TTS requirements from ${UI_TTS_REQUIREMENTS_FILE}"
  if ! "${UI_VENV_PY}" -m pip install --upgrade -r "${UI_TTS_REQUIREMENTS_FILE}"; then
    warn "ui-v7 Kokoro/TTS install failed"
    return 1
  fi
  say "OK: ui-v7 Kokoro/TTS requirements installed"
  return 0
}

download_piper_voice(){
  if [[ -x "${BIN_DIR}/piper" ]]; then
    mkdir -p "${PIPER_DIR}"

    if [[ ! -s "${PIPER_MODEL_PATH}" ]]; then
      if ! download_file "${PIPER_VOICE_ONNX_URL}" "${PIPER_MODEL_PATH}"; then
        warn "failed to download piper voice model; piper may need manual model setup"
      fi
    fi

    if [[ ! -s "${PIPER_MODEL_JSON_PATH}" ]]; then
      if ! download_file "${PIPER_VOICE_JSON_URL}" "${PIPER_MODEL_JSON_PATH}"; then
        warn "failed to download piper voice config"
      fi
    fi

    if [[ -s "${PIPER_MODEL_PATH}" ]]; then
      say "OK: piper voice model present at ${PIPER_MODEL_PATH}"
    fi
  fi
}

main(){
  detect_os
  apt_run

  install_whisper
  download_whisper_model

  if install_piper; then
    download_piper_voice
  else
    warn "no piper runtime detected; voice mode will run without TTS"
  fi
  install_ui_v7_kokoro || warn "ui-v7 Kokoro/TTS not installed; active v7 may fall back from kokoro"

  [[ -x "${BIN_DIR}/whisper" ]] || die "fatal: whisper binary missing after install"
  [[ -s "${WHISPER_MODEL_PATH}" ]] || die "fatal: whisper model missing after install"

  say "DONE: voice engines install complete"
  say "INFO: install prefix ${RUNTIME_DIR}"
  say "INFO: whisper model ${WHISPER_MODEL_PATH}"
}

main "$@"
