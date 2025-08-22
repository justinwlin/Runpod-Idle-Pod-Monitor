#!/usr/bin/env python3
"""
Create an animated GIF demo for RunPod Idle Pod Monitor
Version 2: Better aspect ratio handling and focus on important content
"""

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pathlib import Path

def resize_and_pad(img, target_size=(1280, 720), bg_color=(240, 240, 240)):
    """
    Resize image to fit within target size while maintaining aspect ratio,
    then pad to exact target size
    """
    # Calculate aspect ratios
    img_ratio = img.width / img.height
    target_ratio = target_size[0] / target_size[1]
    
    if img_ratio > target_ratio:
        # Image is wider - fit to width
        new_width = target_size[0]
        new_height = int(new_width / img_ratio)
    else:
        # Image is taller - fit to height
        new_height = target_size[1]
        new_width = int(new_height * img_ratio)
    
    # Resize image
    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Create new image with padding
    new_img = Image.new('RGB', target_size, bg_color)
    
    # Calculate position to center the resized image
    x = (target_size[0] - new_width) // 2
    y = (target_size[1] - new_height) // 2
    
    # Paste resized image onto padded background
    new_img.paste(img_resized, (x, y))
    
    return new_img

def crop_to_important_area(img_path, crop_area=None):
    """
    Crop image to focus on the most important area
    """
    img = Image.open(img_path)
    
    if crop_area:
        # Custom crop area provided (left, top, right, bottom)
        img = img.crop(crop_area)
    
    return img

def create_title_slide(size=(1280, 720)):
    """Create a clean title slide"""
    img = Image.new('RGB', size, color=(20, 30, 48))
    draw = ImageDraw.Draw(img)
    
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 52)
        subtitle_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
        feature_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    except:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        feature_font = ImageFont.load_default()
    
    # Title
    title = "Idle Monitor for RunPod Pods"
    
    # Center text
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_x = (size[0] - (title_bbox[2] - title_bbox[0])) // 2
    
    # Draw text
    draw.text((title_x, 200), title, fill=(255, 255, 255), font=title_font)
    
    # Add key features as bullet points
    points = [
        "• Home Dashboard",
        "• Threshold Configuration for Autostop or Monitoring",
        "• Metrics for Pods", 
        "• Autostop Prediction and Monitoring"
    ]
    
    y = 320
    for point in points:
        # Left-align bullet points for better readability
        draw.text((300, y), point, fill=(130, 180, 255), font=subtitle_font)
        y += 45
    
    return img

def create_features_slide(size=(1280, 720)):
    """Create a clean features slide"""
    img = Image.new('RGB', size, color=(25, 35, 55))
    draw = ImageDraw.Draw(img)
    
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
        feature_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
    except:
        title_font = ImageFont.load_default()
        feature_font = ImageFont.load_default()
    
    title = "Key Features"
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_x = (size[0] - (title_bbox[2] - title_bbox[0])) // 2
    
    draw.text((title_x, 120), title, fill=(255, 255, 255), font=title_font)
    
    # Two column layout for features
    left_features = [
        "📊 Real-time monitoring",
        "⚡ Auto-stop idle pods",
        "📈 Usage analytics"
    ]
    
    right_features = [
        "🛡️ Pod exclusion lists",
        "🔍 Monitor-only mode",
        "🐳 Docker ready"
    ]
    
    # Left column
    y = 220
    for feature in left_features:
        draw.text((150, y), feature, fill=(255, 255, 255), font=feature_font)
        y += 50
    
    # Right column
    y = 220
    for feature in right_features:
        draw.text((650, y), feature, fill=(255, 255, 255), font=feature_font)
        y += 50
    
    # Add bottom text
    bottom_text = "Save money on cloud compute costs"
    bottom_bbox = draw.textbbox((0, 0), bottom_text, font=feature_font)
    bottom_x = (size[0] - (bottom_bbox[2] - bottom_bbox[0])) // 2
    draw.text((bottom_x, 500), bottom_text, fill=(100, 200, 255), font=feature_font)
    
    return img

def add_subtle_caption(img, caption):
    """Add a subtle caption overlay to the bottom of the image"""
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
    except:
        font = ImageFont.load_default()
    
    # Create semi-transparent overlay at bottom
    overlay_height = 80
    overlay = Image.new('RGBA', (img.width, overlay_height), (0, 0, 0, 180))
    
    # Paste overlay at bottom
    img.paste(overlay, (0, img.height - overlay_height), overlay)
    
    # Add caption text
    caption_bbox = draw.textbbox((0, 0), caption, font=font)
    caption_x = (img.width - (caption_bbox[2] - caption_bbox[0])) // 2
    caption_y = img.height - 50
    
    draw.text((caption_x, caption_y), caption, fill=(255, 255, 255), font=font)
    
    return img

def create_demo_gif_v2():
    """Create the animated demo GIF with better proportions"""
    print("🎬 Creating RunPod Monitor Demo GIF (v2)...")
    
    ppt_dir = Path("./ppt")
    output_file = ppt_dir / "runpod-monitor-demo.gif"
    output_file_small = ppt_dir / "runpod-monitor-demo-small.gif"
    
    frames = []
    target_size = (1280, 720)  # 16:9 HD aspect ratio
    
    # Create title slide
    print("📝 Creating title slide...")
    title_slide = create_title_slide(target_size)
    frames.append(title_slide)
    
    # Process dashboard
    print("📸 Processing dashboard.png...")
    dashboard_path = ppt_dir / "dashboard.png"
    if dashboard_path.exists():
        img = Image.open(dashboard_path)
        img_processed = resize_and_pad(img, target_size, bg_color=(245, 245, 245))
        img_with_caption = add_subtle_caption(img_processed, "Home Dashboard")
        frames.append(img_with_caption)
    
    # Process configuration
    print("📸 Processing configuration.png...")
    config_path = ppt_dir / "configuration.png"
    if config_path.exists():
        img = crop_to_important_area(config_path, (0, 0, 2344, 1000))  # Main config area
        img_processed = resize_and_pad(img, target_size, bg_color=(245, 245, 245))
        img_with_caption = add_subtle_caption(img_processed, "Threshold Configuration for Autostop or Monitoring")
        frames.append(img_with_caption)
    
    # Process metrics - show two different parts
    print("📸 Processing metrics.png (pod metrics)...")
    metrics_path = ppt_dir / "metrics.png"
    if metrics_path.exists():
        # First frame: Top statistics section
        img = crop_to_important_area(metrics_path, (0, 0, 2352, 800))  # Active Pod Statistics
        img_processed = resize_and_pad(img, target_size, bg_color=(245, 245, 245))
        img_with_caption = add_subtle_caption(img_processed, "Metrics for Pods")
        frames.append(img_with_caption)
        
        # Second frame: Auto-stop predictions section
        print("📸 Processing metrics.png (autostop predictions)...")
        img = crop_to_important_area(metrics_path, (0, 700, 2352, 1400))  # Auto-stop predictions area
        img_processed = resize_and_pad(img, target_size, bg_color=(245, 245, 245))
        img_with_caption = add_subtle_caption(img_processed, "Autostop Prediction and Monitoring")
        frames.append(img_with_caption)
    
    # Create features slide
    print("✨ Creating features slide...")
    features_slide = create_features_slide(target_size)
    frames.append(features_slide)
    
    # Create end slide with GitHub info
    print("🎬 Creating end slide...")
    end_slide = Image.new('RGB', target_size, color=(15, 25, 40))
    draw = ImageDraw.Draw(end_slide)
    
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
        url_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
    except:
        title_font = ImageFont.load_default()
        url_font = ImageFont.load_default()
    
    title = "Get Started"
    url = "github.com/justinwlin/Runpod-Idle-Pod-Monitor"
    
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_x = (target_size[0] - (title_bbox[2] - title_bbox[0])) // 2
    
    url_bbox = draw.textbbox((0, 0), url, font=url_font)
    url_x = (target_size[0] - (url_bbox[2] - url_bbox[0])) // 2
    
    draw.text((title_x, 280), title, fill=(255, 255, 255), font=title_font)
    draw.text((url_x, 360), url, fill=(100, 180, 255), font=url_font)
    
    frames.append(end_slide)
    
    # Save as animated GIF
    print("💾 Saving animated GIF...")
    if frames:
        # Full size GIF with optimized settings
        frames[0].save(
            output_file,
            save_all=True,
            append_images=frames[1:],
            duration=2500,  # 2.5 seconds per frame
            loop=0,
            optimize=True
        )
        
        # Create smaller version for web
        print("📱 Creating smaller version for web...")
        small_size = (640, 360)
        small_frames = [frame.resize(small_size, Image.Resampling.LANCZOS) for frame in frames]
        small_frames[0].save(
            output_file_small,
            save_all=True,
            append_images=small_frames[1:],
            duration=2500,
            loop=0,
            optimize=True,
            quality=85
        )
        
        print("✅ Demo GIF created successfully!")
        print(f"📁 Output files:")
        print(f"   - Full size (1280x720): {output_file}")
        print(f"   - Small size (640x360): {output_file_small}")
        print("")
        print("📤 Perfect for sharing on:")
        print("   • GitHub README")
        print("   • Twitter/X")
        print("   • Discord/Slack")
        print("   • Documentation")
    else:
        print("❌ No frames created")

if __name__ == "__main__":
    try:
        create_demo_gif_v2()
    except Exception as e:
        print(f"❌ Error: {e}")