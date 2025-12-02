# Lube Change Podcast Image Requirements

## Apple Podcasts Image Specifications

To ensure your podcast image is accepted by Apple Podcasts and other podcast directories, the image must meet these requirements:

### Technical Requirements

- **Dimensions**: Square (1:1 aspect ratio)
  - Minimum: 1400 x 1400 pixels
  - Maximum: 3000 x 3000 pixels
  - Recommended: 3000 x 3000 pixels for best quality

- **File Format**: 
  - JPEG (.jpg) or PNG (.png)
  - JPEG recommended for smaller file size

- **Color Space**: RGB (not CMYK)

- **Resolution**: 72 dpi (recommended)

- **File Size**: Under 500 KB (recommended)

- **Transparency**: No alpha channel (no transparency)

### Content Requirements

- **Original Content**: Must be original artwork or properly licensed
- **No Placeholders**: Cannot use placeholder images
- **Appropriate Content**: No explicit language, illegal activities, or offensive content
- **Clear and Readable**: Text and logos should be clearly visible

### Image File Location

The image should be placed in the repository root as:
```
lubechange-podcast-image.jpg
```

The RSS feed references it at:
```
https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/lubechange-podcast-image.jpg
```

### Preparing Your Oil Filter Image

Since your image is the oil filter with the Edmonton Oilers logo, you'll need to:

1. **Crop to Square**: Ensure the image is square (1:1 aspect ratio)
   - If the original is not square, crop it to center the oil filter
   - Recommended: 3000 x 3000 pixels

2. **Optimize File Size**:
   - Use JPEG format for smaller file size
   - Compress to under 500 KB while maintaining quality
   - Tools: Photoshop, GIMP, or online compressors

3. **Remove Transparency** (if any):
   - Ensure no alpha channel
   - Use a solid background (black matches your theme)

4. **Verify RGB Color Space**:
   - Check in image editor that it's RGB, not CMYK
   - Convert if necessary

5. **Test the Image**:
   - Upload to repository
   - Verify it displays correctly in RSS feed
   - Check that it meets all size requirements

### Image Optimization Tools

- **Online**: TinyPNG, Squoosh, ImageOptim
- **Desktop**: Photoshop, GIMP, ImageMagick
- **Command Line**: 
  ```bash
  # Using ImageMagick to resize and optimize
  convert input.jpg -resize 3000x3000 -quality 85 -strip lubechange-podcast-image.jpg
  ```

### Verification Checklist

Before submitting to Apple Podcasts:

- [ ] Image is square (1:1 aspect ratio)
- [ ] Dimensions are between 1400x1400 and 3000x3000 pixels
- [ ] File format is JPEG or PNG
- [ ] File size is under 500 KB
- [ ] RGB color space (not CMYK)
- [ ] No transparency/alpha channel
- [ ] Image displays correctly in RSS feed
- [ ] Image URL is accessible (returns 200 OK)
- [ ] Image is original or properly licensed

### RSS Feed Image Tag

The RSS feed uses this format:
```xml
<itunes:image href="https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/lubechange-podcast-image.jpg"/>
```

This is automatically updated by the `lubechange.py` script when generating episodes.

