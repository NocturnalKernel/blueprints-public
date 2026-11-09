#!/usr/bin/env python3
"""Unit tests for patch_agy_acp_models.py using a synthetic self-executing .par archive.

Works on any Python 3.9+ interpreter by constructing a deterministic synthetic .pyc
payload with the Python 3.14 magic header (`\\x2b\\x0e\\x0d\\x0a`).
"""

from __future__ import annotations

import _imp
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import patch_agy_acp_models as patcher

PY314_MAGIC = b"\x2b\x0e\x0d\x0a"
PY314_MAGIC_INT = struct.unpack("<I", PY314_MAGIC)[0]


class TestPatchAgyAcpModels(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.par_path = os.path.join(self.tmpdir.name, "agy_acp_server.par")
        self.state_path = os.path.join(self.tmpdir.name, "install-state.json")
        self.backup_dir = os.path.join(self.tmpdir.name, "backups")

        py_source = (
            b"def supports_third_party_models(client):\n  "
            + patcher.ORIG_PY_SNIPPET
            + b"\n"
        )
        source_hash = _imp.source_hash(PY314_MAGIC_INT, py_source)
        if sys.version_info[:2] == (3, 14):
            import marshal

            code_obj = compile(py_source, patcher.PY_MEMBER_NAME, "exec")
            new_consts = []
            for c in code_obj.co_consts:
                if (
                    hasattr(c, "co_name")
                    and c.co_name == "supports_third_party_models"
                ):
                    c = c.replace(co_code=patcher.ORIG_PYC_CODE)
                new_consts.append(c)
            code_obj = code_obj.replace(co_consts=tuple(new_consts))
            pyc_body = marshal.dumps(code_obj)
        else:
            pyc_body = b"synthetic-pyc-prefix-" + patcher.ORIG_PYC_CODE + b"-suffix"

        pyc_header = PY314_MAGIC + struct.pack("<I", 3) + source_hash
        pyc_bytes = pyc_header + pyc_body

        prefix = b"#!/usr/bin/env python3\n# synthetic par stub\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(patcher.PY_MEMBER_NAME, py_source)
            zf.writestr(patcher.PYC_MEMBER_NAME, pyc_bytes)
            zf.writestr("other/module.py", b"x = 1\n")

        with open(self.par_path, "wb") as f:
            f.write(prefix + buf.getvalue())

        st = os.stat(self.par_path)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "installedVersion": "1.3.0",
                    "executableSha256": patcher.sha256_file(self.par_path),
                    "executableSize": st.st_size,
                    "executableMtimeMs": st.st_mtime_ns / 1_000_000.0,
                },
                f,
            )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_check_apply_backup_idempotent_and_revert(self) -> None:
        orig_sha = patcher.sha256_file(self.par_path)

        # 1. Initial check reports unpatched
        st0 = patcher.inspect_status(self.par_path, self.state_path)
        self.assertEqual(st0["state"], "unpatched")
        self.assertTrue(st0["crc_valid"])
        self.assertTrue(st0["pyc"]["source_hash_matches_py"])
        self.assertTrue(st0["install_state_matches"])

        # 2. Apply patch with --backup-dir
        st1 = patcher.transform_par(
            self.par_path, self.state_path, "patched", backup_dir=self.backup_dir
        )
        self.assertEqual(st1["state"], "patched")
        self.assertTrue(st1["crc_valid"])
        self.assertTrue(st1["pyc"]["source_hash_matches_py"])
        self.assertTrue(st1["install_state_matches"])
        self.assertNotEqual(st1["par_sha256"], orig_sha)
        self.assertTrue(
            os.path.isfile(os.path.join(self.backup_dir, "agy_acp_server.par.orig"))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(self.backup_dir, "sha256sums.txt"))
        )

        # 3. Idempotent re-apply
        st2 = patcher.transform_par(self.par_path, self.state_path, "patched")
        self.assertEqual(st2["state"], "patched")
        self.assertEqual(st2["par_sha256"], st1["par_sha256"])

        # 4. Revert restores exact byte-for-byte original SHA-256
        st3 = patcher.transform_par(self.par_path, self.state_path, "unpatched")
        self.assertEqual(st3["state"], "unpatched")
        self.assertTrue(st3["crc_valid"])
        self.assertTrue(st3["pyc"]["source_hash_matches_py"])
        self.assertTrue(st3["install_state_matches"])
        self.assertEqual(st3["par_sha256"], orig_sha)


if __name__ == "__main__":
    unittest.main()
