import math

def rgb_to_lab(rgb):
    """More accurate RGB to LAB conversion"""
    # Normalize RGB to 0-1 range
    r, g, b = [x / 255.0 for x in rgb]
    
    # Convert to XYZ
    r = (r / 12.92) if r <= 0.04045 else ((r + 0.055)/1.055)**2.4
    g = (g / 12.92) if g <= 0.04045 else ((g + 0.055)/1.055)**2.4
    b = (b / 12.92) if b <= 0.04045 else ((b + 0.055)/1.055)**2.4
    
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    
    # D65 illuminant
    x /= 0.95047
    z /= 1.08883
    
    # XYZ to LAB
    epsilon = 0.008856
    kappa = 903.3
    
    fx = x**(1/3) if x > epsilon else (kappa*x + 16)/116
    fy = y**(1/3) if y > epsilon else (kappa*y + 16)/116
    fz = z**(1/3) if z > epsilon else (kappa*z + 16)/116
    
    L = 116*fy - 16
    a = 500*(fx - fy)
    b = 200*(fy - fz)
    
    return (L, a, b)

def delta_e_cie2000(lab1, lab2, Kl=1, Kc=1, Kh=1):
    """Complete CIE2000 implementation"""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    
    # Step 1: Calculate CIELAB ΔL', ΔC', ΔH'
    ΔL = L2 - L1
    
    C1 = math.sqrt(a1**2 + b1**2)
    C2 = math.sqrt(a2**2 + b2**2)
    C_avg = (C1 + C2) / 2
    
    G = 0.5 * (1 - math.sqrt(C_avg**7 / (C_avg**7 + 25**7)))
    a1_prime = a1 * (1 + G)
    a2_prime = a2 * (1 + G)
    
    C1_prime = math.sqrt(a1_prime**2 + b1**2)
    C2_prime = math.sqrt(a2_prime**2 + b2**2)
    ΔC_prime = C2_prime - C1_prime
    
    h1_prime = math.degrees(math.atan2(b1, a1_prime)) % 360
    h2_prime = math.degrees(math.atan2(b2, a2_prime)) % 360
    
    if abs(h1_prime - h2_prime) <= 180:
        Δh_prime = h2_prime - h1_prime
    else:
        Δh_prime = (h2_prime - h1_prime + 360) if h2_prime <= h1_prime else (h2_prime - h1_prime - 360)
    
    ΔH_prime = 2 * math.sqrt(C1_prime * C2_prime) * math.sin(math.radians(Δh_prime) / 2)
    
    # Step 2: Calculate weighting functions
    L_avg_prime = (L1 + L2) / 2
    C_avg_prime = (C1_prime + C2_prime) / 2
    
    if C1_prime * C2_prime == 0:
        h_avg_prime = h1_prime + h2_prime
    else:
        if abs(h1_prime - h2_prime) <= 180:
            h_avg_prime = (h1_prime + h2_prime) / 2
        else:
            h_avg_prime = (h1_prime + h2_prime + 360) / 2 if (h1_prime + h2_prime) < 360 else (h1_prime + h2_prime - 360) / 2
    
    T = (1 - 0.17 * math.cos(math.radians(h_avg_prime - 30))
             + 0.24 * math.cos(math.radians(2 * h_avg_prime))
             + 0.32 * math.cos(math.radians(3 * h_avg_prime + 6))
             - 0.20 * math.cos(math.radians(4 * h_avg_prime - 63)))
    
    S_L = 1 + (0.015 * (L_avg_prime - 50)**2) / math.sqrt(20 + (L_avg_prime - 50)**2)
    S_C = 1 + 0.045 * C_avg_prime
    S_H = 1 + 0.015 * C_avg_prime * T
    
    # Step 3: Calculate RT
    Δθ = 30 * math.exp(-((h_avg_prime - 275) / 25)**2)
    R_C = 2 * math.sqrt(C_avg_prime**7 / (C_avg_prime**7 + 25**7))
    R_T = -math.sin(math.radians(2 * Δθ)) * R_C
    
    # Step 4: Calculate ΔE00
    ΔE00 = math.sqrt(
        (ΔL / (Kl * S_L))**2 +
        (ΔC_prime / (Kc * S_C))**2 +
        (ΔH_prime / (Kh * S_H))**2 +
        R_T * (ΔC_prime / (Kc * S_C)) * (ΔH_prime / (Kh * S_H))
    )
    
    return ΔE00

# Helper function to use with hex codes
def hex_to_lab(hex_color):
    """Convert hex color to LAB"""
    rgb = tuple(int(hex_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    return rgb_to_lab(rgb)

def color_difference(hex1, hex2):
    """Calculate CIE2000 difference between two hex colors"""
    lab1 = hex_to_lab(hex1)
    lab2 = hex_to_lab(hex2)
    return delta_e_cie2000(lab1, lab2)