# Installation Guide

This repository contains the customized `markitdown` package and the `markitdown-ocr` plugin. Install both packages from the cloned source tree.

## Requirements

- Python 3.10 or newer
- Git
- `pip`
- Optional but recommended for audio/video transcription: `ffmpeg`

On Windows with Conda, activate the target environment first:

```powershell
conda activate base
```

## Clone

```powershell
git clone https://github.com/flymi1991/markitdown.git
cd markitdown
```

## Install Core Package

Install the customized MarkItDown package with all optional document-format dependencies:

```powershell
python -m pip install -e "packages/markitdown[all]"
```

This installs support for common formats such as PDF, DOCX, PPTX, XLSX, XLS, Outlook files, YouTube transcript extraction, and Azure-related optional converters.

## Install OCR Plugin

Install the OCR plugin and the OpenAI-compatible client dependency:

```powershell
python -m pip install -e "packages/markitdown-ocr[llm]"
```

The OCR plugin is discovered through the `markitdown.plugin` entry point. Verify it is installed:

```powershell
markitdown --list-plugins
```

Expected output includes:

```text
ocr
```

## Install Audio Transcription Dependencies

For Bilibili/video audio transcription, install the ASR dependencies:

```powershell
python -m pip install funasr torchaudio pydub SpeechRecognition
```

`pydub` needs `ffmpeg` available on `PATH`. Install it separately if audio conversion fails.

## Install SenseVoice Model

Install or copy the SenseVoiceSmall model files into the active Python environment:

```powershell
markitdown --install-sensevoice-model
```

Or install from a local model directory:

```powershell
markitdown --install-sensevoice-model "D:\models\SenseVoiceSmall"
```

The required files, including `model.pt`, are copied to `<python-prefix>\share\markitdown\models`. In a Conda environment this is usually similar to:

```text
D:\Software\Dev\MiniConda\share\markitdown\models
```

## Configure LLMs

Create `markitdown_config.json` next to `markitdown.exe`. In a Conda environment this is usually the environment's `Scripts` directory, for example:

```text
D:\Software\Dev\MiniConda\Scripts\markitdown_config.json
```

Example config:

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

Do not commit real API keys.

## Basic Usage

Convert a local document:

```powershell
markitdown "document.pdf" -o "document.md"
```

Use OCR for standalone JPG/PNG images or images embedded in PDF, DOCX, PPTX, or XLSX:

```powershell
markitdown "document.pdf" --use-plugins -o "document.md"
```

Convert a Bilibili video URL with audio transcription enabled by default:

```powershell
markitdown "https://www.bilibili.com/video/BVxxxxxxx" -o "bilibili.md"
```

## Non-Editable Installation

If you want to delete the cloned source directory after installation, do not use `-e`. Install from Git instead:

```powershell
python -m pip install "git+https://github.com/flymi1991/markitdown.git#subdirectory=packages/markitdown"
python -m pip install "git+https://github.com/flymi1991/markitdown.git#subdirectory=packages/markitdown-ocr"
python -m pip install openai funasr torchaudio pydub SpeechRecognition
```

Confirm the packages are not editable:

```powershell
python -m pip show markitdown
python -m pip show markitdown-ocr
```

The output should not contain `Editable project location`.
