from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _load_chunked_aligner_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "aligner" / "align_folder_chunked.py"
    spec = importlib.util.spec_from_file_location("alex_align_folder_chunked", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_chunked_aligner_exposes_openfst_tool_paths() -> None:
    module = _load_chunked_aligner_module()
    block = module.speech_path_block()

    assert "$KALDI_ROOT_ABS/tools/openfst-1.8.4/bin" in block
    assert "$KALDI_ROOT_ABS/tools/openfst/bin" in block
    assert "KALDI_ROOT_ABS" in block
    assert "find -L" in block
    assert "DYLD_LIBRARY_PATH" in block
    assert "command -v fstcompile" in block


def test_speech_engine_lib_dir_uses_relative_symlinks(tmp_path: Path) -> None:
    module = _load_chunked_aligner_module()
    decoder = tmp_path / "src" / "decoder"
    decoder.mkdir(parents=True)
    (decoder / "libkaldi-decoder.dylib").write_bytes(b"placeholder")

    module.ensure_speech_engine_lib_dir(tmp_path)
    module.ensure_speech_engine_lib_dir(tmp_path)

    link = tmp_path / "src" / "lib" / "libkaldi-decoder.dylib"
    assert link.is_symlink()
    assert Path(os.readlink(link)) == Path("..") / "decoder" / "libkaldi-decoder.dylib"
