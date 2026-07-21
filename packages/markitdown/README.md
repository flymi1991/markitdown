# MarkItDown Video/ASR Edition

> [!TIP]
> This package is based on Microsoft's open-source MarkItDown and adds Bilibili/YouTube video-to-Markdown, local SenseVoice ASR, and optional OpenAI-compatible LLM transcript correction.
>
> For more information, and full documentation, see the project [README.md](https://github.com/microsoft/markitdown) on GitHub.

> [!IMPORTANT]
> MarkItDown performs I/O with the privileges of the current process. Like open() or requests.get(), it will access resources that the process itself can access. Sanitize your inputs in untrusted environments, and call the narrowest `convert_*` function needed for your use case (e.g., `convert_stream()`, or `convert_local()`). See the [Security Considerations](https://github.com/microsoft/markitdown#security-considerations) section of the documentation for more information.

## Installation

From PyPI:

```bash
pip install markitdown[all]
```

From source:

```bash
git clone git@github.com:microsoft/markitdown.git
cd markitdown
pip install -e packages/markitdown[all]
```

## Usage

### Command-Line

```bash
markitdown path-to-file.pdf > document.md
```

### Python API

```python
from markitdown import MarkItDown

md = MarkItDown()
result = md.convert("test.xlsx")
print(result.text_content)
```

### Bilibili Video To Markdown

For Bilibili video URLs, the CLI enables audio transcription by default:

```bash
markitdown "https://www.bilibili.com/video/BVxxxxxxx" -o bilibili_output.md
```

Interactive mode is also supported:

```bash
markitdown
Input file path or URL: https://www.bilibili.com/video/BVxxxxxxx
Output Markdown file path: bilibili_output.md
```

Optional controls:

```bash
markitdown "https://www.bilibili.com/video/BVxxxxxxx" -o bilibili_output.md --sensevoice-workers 8
markitdown "https://www.bilibili.com/video/BVxxxxxxx" -o bilibili_output.md --no-bilibili-audio
```

```python
from markitdown import MarkItDown

md = MarkItDown()
result = md.convert(
    "https://www.bilibili.com/video/BVxxxxxxx",
    bilibili_transcribe_audio=True,
    sensevoice_workers=8,
)
print(result.text_content)
```

The generated Markdown includes the original source URL, video metadata, description, and transcript when subtitles or audio transcription are available.

### Local SenseVoice Model

SenseVoice is used as the primary ASR backend when `funasr` is installed. The loader checks:

1. `MARKITDOWN_SENSEVOICE_MODEL`
2. The `markitdown.exe` directory itself
3. `SenseVoiceSmall` under the `markitdown.exe` directory
4. `models/SenseVoiceSmall` under the `markitdown.exe` directory
5. `<python-prefix>/share/markitdown/models/SenseVoiceSmall`
6. Package-local model directory
7. Source-tree directory: `packages/markitdown/models/SenseVoiceSmall`
8. `iic/SenseVoiceSmall` via ModelScope

Install/copy the model files next to `markitdown.exe`:

```bash
markitdown --install-sensevoice-model
```

Or pass a model directory explicitly:

```bash
markitdown --install-sensevoice-model "D:/models/SenseVoiceSmall"
```

After this, `markitdown.exe` can be run from any directory without relying on the source project path.

For portable sharing, include the SenseVoice model files in `packages/markitdown/models/SenseVoiceSmall`.

If `model.pt` is not already present, download it from ModelScope:

```text
https://www.modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt
```

For an installed environment, save it next to `markitdown.exe`:

```text
<markitdown.exe directory>/model.pt
```

Keep the related SenseVoice config/token files in the same directory. If they are missing, download the full `iic/SenseVoiceSmall` snapshot from ModelScope or let `funasr` download it once, then copy the files next to `markitdown.exe`.

### LLM Transcript Correction

The package can auto-load OpenAI-compatible LLM settings from `markitdown_config.json`:

```json
{
  "llm": {
    "api_key": "YOUR_API_KEY",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat"
  }
}
```

The config file is discovered from the `markitdown.exe` directory first, then from the active Python environment's `Scripts` directory, and then from the current working directory or its parents. This lets an installed `markitdown.exe` run without depending on the source checkout path.

When configured, Bilibili ASR transcripts are corrected with an LLM by default unless `bilibili_correct_transcript=False` is passed.

### OCR LLM Configuration

When `markitdown-ocr` is installed and plugins are enabled, OCR reads its own OpenAI-compatible settings from the `ocr_llm` section in `markitdown_config.json`:

```json
{
  "llm": {
    "api_key": "YOUR_TRANSCRIPT_API_KEY",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat"
  },
  "ocr_llm": {
    "api_key": "YOUR_OCR_API_KEY",
    "base_url": "https://your-openai-compatible-endpoint.example",
    "model": "your-vision-model"
  }
}
```

Run OCR with plugins enabled:

```bash
markitdown document.pdf --use-plugins
```

The OCR plugin does not require `--llm-client openai` or `--llm-model`; it uses `ocr_llm` from the config file.

Do not commit real API keys.

### More Information

For more information, and full documentation, see the project [README.md](https://github.com/microsoft/markitdown) on GitHub.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
