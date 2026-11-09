#!/usr/bin/env python3
"""Enable third-party (Claude 5.5 / GPT-OSS) models in Happier's managed agy_acp_server.par.

Google's Antigravity ACP server (`agy_acp_server.par`, Python 3.14 autopar) gates
non-Gemini models behind `supports_third_party_models(client)` in:
  - google3/cloud/developer_experience/antigravity_extensions/acp_server/model_selection.py
  - google3/cloud/developer_experience/antigravity_extensions/acp_server/__pycache__/model_selection.cpython-314.pyc

By default:
  return client.is_jetbrains or client.is_zed or client.is_xcode

Happier connects with `clientInfo.name = "happier-cli"` (or `"happier-cli-capabilities"`),
causing `_parse_ccpa_response` to strip `claude-*` models and `_apply_session_model` to
reject them.

This script performs an atomic, same-length patch on both the uncompressed `.py` source
member (62-byte replacement) and the uncompressed `.pyc` bytecode member (PEP 552
source_hash update + 106-byte `co_code` replacement returning `True`), updates the
Local File Header and Central Directory Header CRC32 fields for both members, atomically
replaces `agy_acp_server.par` via `os.replace`, and synchronizes `install-state.json`
(`executableSha256`, `executableSize`, `executableMtimeMs`).

Path-agnostic and host-Python-version independent (works under any Python 3.9+ on Linux/macOS).
"""

from __future__ import annotations

import _imp
import argparse
import hashlib
import importlib.util
import json
import marshal
import os
import re
import shutil
import struct
import subprocess
import sys
import types
import zipfile
import zlib

PY_MEMBER_NAME = (
    "google3/cloud/developer_experience/antigravity_extensions/"
    "acp_server/model_selection.py"
)
PYC_MEMBER_NAME = (
    "google3/cloud/developer_experience/antigravity_extensions/"
    "acp_server/__pycache__/model_selection.cpython-314.pyc"
)

ORIG_PY_SNIPPET = b"return client.is_jetbrains or client.is_zed or client.is_xcode"
PATCH_PY_SNIPPET = b"return True # is_jetbrains or client.is_zed or client.is_xcode"
assert len(ORIG_PY_SNIPPET) == len(PATCH_PY_SNIPPET) == 62

# Python 3.14 bytecode for supports_third_party_models(client) (106 bytes)
ORIG_PYC_CODE = bytes.fromhex(
    "8000560050000000000000000000000000000000000000003b012700000000000000"
    "672100001c001f00560050020000000000000000000000000000000000003b012700"
    "000000000000670d00001c001f005600500400000000000000000000000000000000"
    "00002300"
)
# Replacement: RESUME 0 (80 00), LOAD_SMALL_INT 1 (5e 01),
# TO_BOOL + 3 inline cache words (27 00 0000 0000 0000), RETURN_VALUE (23 00),
# padded with NOP (1e 00) to 106 bytes.
_PATCH_PYC_PREFIX = bytes.fromhex("80005e0127000000000000002300")
PATCH_PYC_CODE = _PATCH_PYC_PREFIX + (
    b"\x1e\x00" * ((len(ORIG_PYC_CODE) - len(_PATCH_PYC_PREFIX)) // 2)
)
assert len(ORIG_PYC_CODE) == len(PATCH_PYC_CODE) == 106


def discover_happier_home() -> str:
    """Resolve the active Happier home directory without hardcoded user paths."""
    env_home = os.environ.get("HAPPIER_HOME_DIR", "").strip()
    if env_home and os.path.isdir(os.path.expanduser(env_home)):
        return os.path.abspath(os.path.expanduser(env_home))

    # Check user systemd unit environment if systemctl is available
    try:
        out = subprocess.check_output(
            ["systemctl", "--user", "cat", "happier-daemon.default.service"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        m = re.search(r"^Environment=HAPPIER_HOME_DIR=(.+)$", out, re.MULTILINE)
        if m:
            candidate = os.path.expanduser(m.group(1).strip().strip('"'))
            if os.path.isdir(candidate):
                return os.path.abspath(candidate)
    except Exception:
        pass

    return os.path.abspath(os.path.expanduser("~/.happier"))


def default_paths() -> tuple[str, str]:
    base = discover_happier_home()
    par_path = os.path.join(
        base, "tools", "agy-acp-server", "current", "agy_acp_server.par"
    )
    state_path = os.path.join(base, "tools", "agy-acp-server", "install-state.json")
    return par_path, state_path


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def locate_member(
    par_path: str,
    member_name: str,
    orig_snippet: bytes,
    patch_snippet: bytes,
) -> dict:
    with zipfile.ZipFile(par_path, "r") as zf:
        info = zf.getinfo(member_name)
        if info.compress_type != zipfile.ZIP_STORED:
            raise ValueError(
                f"{member_name} is compressed (type={info.compress_type}); "
                "in-place patch requires ZIP_STORED (0)"
            )
        header_offset = info.header_offset
        file_size = info.file_size
        reported_crc = info.CRC

    with open(par_path, "rb") as f:
        f.seek(header_offset)
        lh = f.read(30)
        if lh[:4] != b"PK\x03\x04":
            raise ValueError(f"Invalid local file header magic at {header_offset}")
        lh_crc = struct.unpack("<I", lh[14:18])[0]
        fname_len, extra_len = struct.unpack("<HH", lh[26:30])
        data_offset = header_offset + 30 + fname_len + extra_len
        local_crc_offset = header_offset + 14

        f.seek(data_offset)
        data = f.read(file_size)
        if len(data) != file_size:
            raise ValueError("Truncated member data")

        file_len = os.path.getsize(par_path)
        search_size = min(file_len, 128 * 1024 * 1024)
        f.seek(file_len - search_size)
        tail = f.read(search_size)
        tail_base = file_len - search_size

        target_name_bytes = member_name.encode("utf-8")
        cd_sig = b"PK\x01\x02"
        cd_crc_offset = None
        cd_crc = None
        pos = 0
        while True:
            idx = tail.find(cd_sig, pos)
            if idx == -1:
                break
            if idx + 46 <= len(tail):
                cd_fname_len, _, _ = struct.unpack("<HHH", tail[idx + 28 : idx + 34])
                entry_crc = struct.unpack("<I", tail[idx + 16 : idx + 20])[0]
                entry_size = struct.unpack("<I", tail[idx + 24 : idx + 28])[0]
                name_start = idx + 46
                name_end = name_start + cd_fname_len
                if (
                    name_end <= len(tail)
                    and tail[name_start:name_end] == target_name_bytes
                    and entry_size == file_size
                ):
                    cd_crc_offset = tail_base + idx + 16
                    cd_crc = entry_crc
                    break
            pos = idx + 1

        if cd_crc_offset is None or cd_crc is None:
            raise ValueError(f"Central directory entry not found for {member_name}")

    actual_crc = zlib.crc32(data) & 0xFFFFFFFF
    if orig_snippet in data and patch_snippet not in data:
        state = "unpatched"
        snippet_offset = data_offset + data.index(orig_snippet)
    elif patch_snippet in data and orig_snippet not in data:
        state = "patched"
        snippet_offset = data_offset + data.index(patch_snippet)
    else:
        raise ValueError(
            f"Neither expected original nor patched snippet found in {member_name}"
        )

    return {
        "member_name": member_name,
        "state": state,
        "header_offset": header_offset,
        "data_offset": data_offset,
        "file_size": file_size,
        "snippet_offset": snippet_offset,
        "local_crc_offset": local_crc_offset,
        "cd_crc_offset": cd_crc_offset,
        "lh_crc": lh_crc,
        "cd_crc": cd_crc,
        "reported_crc": reported_crc,
        "actual_crc": actual_crc,
        "data": data,
    }


def compute_pep552_source_hash(pyc_header_bytes: bytes, source_bytes: bytes) -> bytes:
    """Compute PEP 552 SipHash-2-4 using the magic number embedded in the .pyc header.

    This guarantees the exact Python 3.14 source_hash even when the patcher script
    itself is executed by an older host Python interpreter (e.g. Python 3.10-3.13).
    """
    magic_int = struct.unpack("<I", pyc_header_bytes[:4])[0]
    return _imp.source_hash(magic_int, source_bytes)


def sync_install_state(par_path: str, state_path: str) -> dict | None:
    if not state_path or not os.path.exists(state_path):
        return None
    st = os.stat(par_path)
    digest = sha256_file(par_path)
    mtime_ms = st.st_mtime_ns / 1_000_000.0
    with open(state_path, "r", encoding="utf-8") as f:
        state_data = json.load(f)
    state_data["executableSha256"] = digest
    state_data["executableSize"] = st.st_size
    state_data["executableMtimeMs"] = mtime_ms
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)
        f.write("\n")
    return state_data


def create_backup(par_path: str, state_path: str | None, backup_dir: str) -> dict:
    backup_dir = os.path.abspath(os.path.expanduser(backup_dir))
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    os.chmod(backup_dir, 0o700)

    par_bak = os.path.join(backup_dir, "agy_acp_server.par.orig")
    state_bak = os.path.join(backup_dir, "install-state.json.orig")
    manifest_path = os.path.join(backup_dir, "sha256sums.txt")

    if not os.path.exists(par_bak):
        shutil.copy2(par_path, par_bak)
        os.chmod(par_bak, 0o600)
    if state_path and os.path.exists(state_path) and not os.path.exists(state_bak):
        shutil.copy2(state_path, state_bak)
        os.chmod(state_bak, 0o600)

    lines = [f"{sha256_file(par_bak)}  agy_acp_server.par.orig"]
    if os.path.exists(state_bak):
        lines.append(f"{sha256_file(state_bak)}  install-state.json.orig")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(manifest_path, 0o600)

    return {
        "backup_dir": backup_dir,
        "par_backup": par_bak,
        "state_backup": state_bak if os.path.exists(state_bak) else None,
        "manifest": manifest_path,
    }


def inspect_status(par_path: str, state_path: str | None = None) -> dict:
    py_info = locate_member(par_path, PY_MEMBER_NAME, ORIG_PY_SNIPPET, PATCH_PY_SNIPPET)
    pyc_info = locate_member(
        par_path, PYC_MEMBER_NAME, ORIG_PYC_CODE, PATCH_PYC_CODE
    )
    expected_source_hash = compute_pep552_source_hash(
        pyc_info["data"][:4], py_info["data"]
    )
    actual_source_hash = pyc_info["data"][8:16]
    source_hash_matches = expected_source_hash == actual_source_hash

    par_sha256 = sha256_file(par_path)
    st = os.stat(par_path)
    state_match = None
    state_sha256 = None
    if state_path and os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            sd = json.load(f)
        state_sha256 = sd.get("executableSha256")
        state_match = (
            state_sha256 == par_sha256 and sd.get("executableSize") == st.st_size
        )

    overall_state = (
        py_info["state"]
        if py_info["state"] == pyc_info["state"]
        else f"mixed(py={py_info['state']},pyc={pyc_info['state']})"
    )
    crc_valid = (
        py_info["actual_crc"] == py_info["lh_crc"] == py_info["cd_crc"]
        and pyc_info["actual_crc"] == pyc_info["lh_crc"] == pyc_info["cd_crc"]
    )
    return {
        "par_path": par_path,
        "state": overall_state,
        "py": {
            "state": py_info["state"],
            "snippet_offset": py_info["snippet_offset"],
            "local_crc_offset": py_info["local_crc_offset"],
            "cd_crc_offset": py_info["cd_crc_offset"],
            "crc32_hex": f"0x{py_info['actual_crc']:08x}",
        },
        "pyc": {
            "state": pyc_info["state"],
            "snippet_offset": pyc_info["snippet_offset"],
            "source_hash_offset": pyc_info["data_offset"] + 8,
            "source_hash_hex": actual_source_hash.hex(),
            "source_hash_matches_py": source_hash_matches,
            "local_crc_offset": pyc_info["local_crc_offset"],
            "cd_crc_offset": pyc_info["cd_crc_offset"],
            "crc32_hex": f"0x{pyc_info['actual_crc']:08x}",
        },
        "crc_valid": crc_valid,
        "par_sha256": par_sha256,
        "par_size": st.st_size,
        "install_state_path": state_path,
        "install_state_sha256": state_sha256,
        "install_state_matches": state_match,
    }


def transform_par(
    par_path: str,
    state_path: str | None,
    target_state: str,
    backup_dir: str | None = None,
) -> dict:
    if target_state not in ("patched", "unpatched"):
        raise ValueError(f"Invalid target_state: {target_state}")

    py_info = locate_member(par_path, PY_MEMBER_NAME, ORIG_PY_SNIPPET, PATCH_PY_SNIPPET)
    pyc_info = locate_member(
        par_path, PYC_MEMBER_NAME, ORIG_PYC_CODE, PATCH_PYC_CODE
    )

    backup_info = None
    if backup_dir and py_info["state"] == "unpatched" and target_state == "patched":
        backup_info = create_backup(par_path, state_path, backup_dir)

    if py_info["state"] != target_state or pyc_info["state"] != target_state:
        # 1. Transform .py member bytes
        py_data = py_info["data"]
        if target_state == "patched":
            new_py_data = py_data.replace(ORIG_PY_SNIPPET, PATCH_PY_SNIPPET, 1)
            py_replacement = PATCH_PY_SNIPPET
        else:
            new_py_data = py_data.replace(PATCH_PY_SNIPPET, ORIG_PY_SNIPPET, 1)
            py_replacement = ORIG_PY_SNIPPET
        new_py_crc = zlib.crc32(new_py_data) & 0xFFFFFFFF
        new_py_crc_bytes = struct.pack("<I", new_py_crc)

        # 2. Transform .pyc member bytes (both PEP 552 source_hash at [8:16] and co_code)
        pyc_data = pyc_info["data"]
        new_source_hash = compute_pep552_source_hash(pyc_data[:4], new_py_data)
        if target_state == "patched":
            new_pyc_body = pyc_data.replace(ORIG_PYC_CODE, PATCH_PYC_CODE, 1)
            pyc_replacement = PATCH_PYC_CODE
        else:
            new_pyc_body = pyc_data.replace(PATCH_PYC_CODE, ORIG_PYC_CODE, 1)
            pyc_replacement = ORIG_PYC_CODE
        new_pyc_data = new_pyc_body[:8] + new_source_hash + new_pyc_body[16:]
        new_pyc_crc = zlib.crc32(new_pyc_data) & 0xFFFFFFFF
        new_pyc_crc_bytes = struct.pack("<I", new_pyc_crc)

        tmp_path = f"{par_path}.tmp.{os.getpid()}"
        try:
            shutil.copyfile(par_path, tmp_path)
            shutil.copymode(par_path, tmp_path)
            with open(tmp_path, "r+b") as f:
                # Write .py changes
                f.seek(py_info["snippet_offset"])
                f.write(py_replacement)
                f.seek(py_info["local_crc_offset"])
                f.write(new_py_crc_bytes)
                f.seek(py_info["cd_crc_offset"])
                f.write(new_py_crc_bytes)

                # Write .pyc changes (source_hash, co_code, local CRC, CD CRC)
                f.seek(pyc_info["data_offset"] + 8)
                f.write(new_source_hash)
                f.seek(pyc_info["snippet_offset"])
                f.write(pyc_replacement)
                f.seek(pyc_info["local_crc_offset"])
                f.write(new_pyc_crc_bytes)
                f.seek(pyc_info["cd_crc_offset"])
                f.write(new_pyc_crc_bytes)
                f.flush()
                os.fsync(f.fileno())

            # Verify both ZIP members via zipfile CRC check on staged file
            with zipfile.ZipFile(tmp_path, "r") as zf:
                verified_py = zf.read(PY_MEMBER_NAME)
                verified_pyc = zf.read(PYC_MEMBER_NAME)
            if verified_py != new_py_data or verified_pyc != new_pyc_data:
                raise RuntimeError("Post-patch ZIP member verification mismatch")

            # If host Python matches the .pyc magic (Python 3.14), also test-execute the code object
            if importlib.util.MAGIC_NUMBER == verified_pyc[:4]:
                mod_code = marshal.loads(verified_pyc[16:])
                found_fn = False
                for c in mod_code.co_consts:
                    if (
                        hasattr(c, "co_name")
                        and c.co_name == "supports_third_party_models"
                    ):
                        found_fn = True
                        if target_state == "patched":
                            fn = types.FunctionType(c, {})
                            if fn(None) is not True:
                                raise RuntimeError(
                                    "Patched supports_third_party_models did not return True"
                                )
                if not found_fn:
                    raise RuntimeError(
                        "supports_third_party_models code object missing in .pyc"
                    )

            os.replace(tmp_path, par_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    if state_path:
        sync_install_state(par_path, state_path)

    status = inspect_status(par_path, state_path)
    if backup_info:
        status["backup"] = backup_info
    return status


def main(argv: list[str] | None = None) -> int:
    def_par, def_state = default_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check",
        action="store_true",
        help="Check patch status and install-state consistency (read-only)",
    )
    group.add_argument(
        "--apply",
        action="store_true",
        help="Apply the third-party models patch and update install-state.json",
    )
    group.add_argument(
        "--revert",
        action="store_true",
        help="Revert the patch back to upstream bytes and update install-state.json",
    )
    parser.add_argument(
        "--par-path",
        default=def_par,
        help="Path to agy_acp_server.par (auto-discovered via $HAPPIER_HOME_DIR or ~/.happier)",
    )
    parser.add_argument(
        "--state-path",
        default=def_state,
        help="Path to install-state.json (pass '' to skip)",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="Optional directory to store .orig backups and sha256sums.txt before --apply",
    )
    args = parser.parse_args(argv)
    par_path = os.path.abspath(os.path.expanduser(args.par_path))
    state_path = (
        os.path.abspath(os.path.expanduser(args.state_path))
        if args.state_path
        else None
    )

    if args.check:
        status = inspect_status(par_path, state_path)
        print(json.dumps(status, indent=2))
        ok = (
            status["state"] == "patched"
            and status["crc_valid"]
            and status["pyc"]["source_hash_matches_py"]
            and status["install_state_matches"] is not False
        )
        return 0 if ok else 1

    if args.apply:
        status = transform_par(
            par_path, state_path, "patched", backup_dir=args.backup_dir
        )
        print(json.dumps(status, indent=2))
        return 0

    if args.revert:
        status = transform_par(par_path, state_path, "unpatched")
        print(json.dumps(status, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
