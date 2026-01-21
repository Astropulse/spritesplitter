# Sprite Extractor

Extract individual sprites from a sprite sheet by finding connected components on a downscaled occupancy mask using 8 connectivity, then cropping each component and zeroing alpha outside the component.

The tool writes one PNG per extracted sprite and an atlas.json describing the results. It is designed to be run directly from the command line.

<img width="1152" height="512" alt="demo" src="https://github.com/user-attachments/assets/e4445866-1edf-49dd-985c-f2203d931bad" />

## How it works

1. Build a per pixel foreground mask
   - If the input image has an alpha channel, foreground is alpha greater than zero.
   - Otherwise, background is assumed to be the most common RGB color in the image, and foreground is any pixel not equal to that color.

2. Downscale the foreground mask into a tile grid
   - Each tile covers tile by tile pixels.
   - A tile is marked foreground if any pixel inside it is foreground.

3. Flood fill connected components on the tile grid using 8 connectivity.

4. For each component
   - Compute its bounding box in pixel space.
   - Crop the original RGBA image to that box.
   - Set alpha to zero for any pixel not belonging to the component.

## Requirements

- Python 3.9 or newer
- Pillow

Install dependencies:

    python3 -m pip install pillow

## Usage

Basic usage:

    python3 sprite_extractor.py sheet.png

Specify output directory and tile size:

    python3 sprite_extractor.py sheet.png --out out --tile 2

Write the atlas JSON under a different name:

    python3 sprite_extractor.py sheet.png --out out --atlas my_atlas.json

Sort extracted sprites:

- topleft (default): roughly reading order by component bounding box
- size: largest components first
- none: discovery order from flood fill

Example:

    python3 sprite_extractor.py sheet.png --sort size

Filter out small components measured in mask tiles:

    python3 sprite_extractor.py sheet.png --min-cells 4

Disable labeling entirely:

    python3 sprite_extractor.py sheet.png --no-label

## Output

The output directory contains:

- sprite_0000.png, sprite_0001.png, and so on
- atlas.json or the filename specified with --atlas

Example atlas.json:

    {
      "meta": {
        "source": "sheet.png",
        "image_w": 1024,
        "image_h": 512,
        "tile": 2,
        "mask_w": 512,
        "mask_h": 256,
        "count": 42
      },
      "sprites": [
        {
          "id": 0,
          "name": "sprite_0000",
          "x": 10,
          "y": 24,
          "w": 32,
          "h": 32,
          "mask_x": 5,
          "mask_y": 12,
          "mask_w": 16,
          "mask_h": 16,
          "image": "sprite_0000.png"
        }
      ]
    }

Field meanings:

- x, y, w, h: pixel bounding box in the original sheet
- mask_x, mask_y, mask_w, mask_h: bounding box in tile coordinates
- image: filename written to the output directory
- name: label for the sprite
  - By default this comes from a placeholder labeler function.
  - Use --no-label to skip labeling.
