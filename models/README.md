# Models

Model weights are intentionally not committed to this repository.

## YOLO date-stamp detector

The optional YOLO adapter accepts local Ultralytics-compatible weights. Configure the path in `config/settings.yaml`.

A publicly available model such as `pike00/yolo-date-stamp-detector` may be evaluated as an optional detector. Its documented training domain is limited; do not assume it detects all colors, layouts, handwritten dates, Polaroid borders, or non-North-American formats. Review the model card and AGPL-3.0 license before use.

## Ollama

Enable the local Ollama fallback in the configuration and set the model name available on your machine. The vision model must support image input. Requests are sent only to the configured local Ollama endpoint.
