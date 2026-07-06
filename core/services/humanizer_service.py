import random
import math
import logging
from typing import List, Tuple, Generator
from core.models.recoil_data import RecoilData
from core.models.weapon import WeaponProfile

class PerlinNoise1D:
    """1D Perlin Noise generator for organic drift simulation."""
    def __init__(self):
        self.gradients = [random.uniform(-1.0, 1.0) for _ in range(256)]

    def _lerp(self, a: float, b: float, t: float) -> float:
        return a + t * (b - a)

    def _fade(self, t: float) -> float:
        # Smootherstep: 6t^5 - 15t^4 + 10t^3
        return t * t * t * (t * (t * 6 - 15) + 10)

    def noise(self, x: float) -> float:
        x0 = int(math.floor(x))
        x1 = x0 + 1
        
        dx0 = x - x0
        dx1 = x - x1

        i0 = x0 & 255
        i1 = x1 & 255

        g0 = self.gradients[i0]
        g1 = self.gradients[i1]

        v0 = g0 * dx0
        v1 = g1 * dx1

        t = self._fade(dx0)
        return self._lerp(v0, v1, t)

class HumanizerEngine:
    """Enterprise-grade ultimate humanizer for recoil compensation."""

    def __init__(self):
        self.logger = logging.getLogger("HumanizerEngine")
        self.perlin_x = PerlinNoise1D()
        self.perlin_y = PerlinNoise1D()

    @staticmethod
    def _catmull_rom_spline(p0: float, p1: float, p2: float, p3: float, t: float, tension: float = 0.5) -> float:
        """Catmull-Rom spline with variable tension."""
        t2 = t * t
        t3 = t2 * t
        
        # Adjusting matrix for tension. Standard Catmull-Rom has tension = 0.5.
        alpha = tension * 2.0 
        
        return 0.5 * ((2 * p1) +
                      (-p0 + p2) * t * alpha +
                      (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                      (-p0 + 3 * p1 - 3 * p2 + p3) * t3)

    @staticmethod
    def _smoothstep(t: float) -> float:
        """Velocity profile easing (acceleration/deceleration). Minimum Jerk approximation."""
        # Cubic Hermite interpolation (3t^2 - 2t^3)
        return t * t * (3.0 - 2.0 * t)

    def generate_runtime_sequence(self, 
                                  weapon: WeaponProfile, 
                                  raw_pattern: List[RecoilData], 
                                  min_step: float = 6.0, 
                                  max_step: float = 12.0,
                                  tension: float = 0.5,
                                  overshoot_prob: float = 0.1) -> Generator[RecoilData, None, None]:
        """
        Generate a fully randomized, smoothed micro-stepped sequence.
        This must be called at runtime (when trigger is pressed) to ensure uniqueness.
        """
        if not raw_pattern:
            return

        # Use pre-calculated absolute path from WeaponProfile
        abs_points_x = weapon.abs_points_x
        abs_points_y = weapon.abs_points_y
        
        if not abs_points_x or len(abs_points_x) < 4:
            self.logger.warning("Missing or invalid absolute path points in WeaponProfile")
            return

        
        # Max drift amplitude derived from jitter_movement
        max_drift = max(1.0, weapon.jitter_movement / 5.0) 
        
        # Random noise offsets
        noise_offset_x = random.uniform(0, 1000)
        noise_offset_y = random.uniform(0, 1000)
        noise_speed = 0.15 # Frequency of the pink noise

        prev_smooth_x, prev_smooth_y = 0.0, 0.0
        total_time_ms = 0.0

        for i, point in enumerate(raw_pattern):
            # Calculate base delay mathematically equivalent to old subdivide
            base_delay = weapon.multiple * (point.delay / weapon.sleep_divider - weapon.sleep_suber)
            if base_delay <= 0:
                base_delay = 1.0

            # Add macro timing jitter for this bullet
            if weapon.jitter_timing > 0:
                std_dev = weapon.jitter_timing / 3.0
                base_delay += random.gauss(0, std_dev)
                base_delay = max(1.0, base_delay)

            # Determine number of micro-steps
            target_step_time = random.uniform(min_step, max_step)
            num_steps = max(1, int(base_delay / target_step_time))

            # Generate random time fractions that sum to 1.0
            fractions = [random.uniform(0.5, 1.5) for _ in range(num_steps)]
            total_fraction = sum(fractions)
            time_steps = [(f / total_fraction) * base_delay for f in fractions]

            current_t = 0.0
            
            # Overshoot target calculation
            overshoot_active = False
            overshoot_factor_x = 0.0
            overshoot_factor_y = 0.0
            
            if random.random() < overshoot_prob:
                overshoot_active = True
                overshoot_factor_x = random.uniform(-0.15, 0.15) # Overshoot up to 15% of vector
                overshoot_factor_y = random.uniform(-0.15, 0.15)
            
            for step_time in time_steps:
                current_t += (step_time / base_delay)
                t = min(1.0, current_t)
                
                # Apply velocity curve (Smoothstep) to simulate acceleration/deceleration
                eased_t = self._smoothstep(t)

                # Interpolation points
                p0_x, p1_x, p2_x, p3_x = abs_points_x[i], abs_points_x[i+1], abs_points_x[i+2], abs_points_x[i+3]
                p0_y, p1_y, p2_y, p3_y = abs_points_y[i], abs_points_y[i+1], abs_points_y[i+2], abs_points_y[i+3]

                smooth_x = self._catmull_rom_spline(p0_x, p1_x, p2_x, p3_x, eased_t, tension)
                smooth_y = self._catmull_rom_spline(p0_y, p1_y, p2_y, p3_y, eased_t, tension)

                # Apply Overshoot dynamics if active
                if overshoot_active:
                    # Overshoot peaks at mid-movement and corrects back by t=1.0
                    overshoot_envelope = math.sin(t * math.pi) 
                    delta_x = p2_x - p1_x
                    delta_y = p2_y - p1_y
                    smooth_x += delta_x * overshoot_factor_x * overshoot_envelope
                    smooth_y += delta_y * overshoot_factor_y * overshoot_envelope

                # Apply Perlin Noise Drift
                total_time_ms += step_time
                noise_x = self.perlin_x.noise(noise_offset_x + total_time_ms * noise_speed * 0.01) * max_drift
                noise_y = self.perlin_y.noise(noise_offset_y + total_time_ms * noise_speed * 0.01) * max_drift
                
                final_x = smooth_x + noise_x
                final_y = smooth_y + noise_y

                step_dx = final_x - prev_smooth_x
                step_dy = final_y - prev_smooth_y

                yield RecoilData(
                    dx=step_dx,
                    dy=step_dy,
                    delay=step_time
                )

                prev_smooth_x = final_x
                prev_smooth_y = final_y

    def generate_return_sequence(self, total_dx: float, total_dy: float, duration_ms: float = 250.0, return_ratio: float = 1.0) -> Generator[RecoilData, None, None]:
        """
        Generate a smooth cubic ease-out sequence to return the mouse to the center,
        scaling the Y return by return_ratio (0.0 to 1.0).
        """
        if duration_ms <= 0:
            return
            
        target_dx = -total_dx
        target_dy = -total_dy * max(0.0, min(1.0, return_ratio))
        
        if abs(target_dx) < 1.0 and abs(target_dy) < 1.0:
            return

        # Average step time ~ 10ms
        num_steps = max(1, int(duration_ms / 10.0))
        
        # Add a tiny bit of pink noise to the return path to avoid straight robotic lines
        noise_offset_x = random.uniform(0, 1000)
        noise_offset_y = random.uniform(0, 1000)
        noise_speed = 0.15
        max_drift = 2.0 # Tiny drift for return path

        prev_x, prev_y = 0.0, 0.0
        total_time_ms = 0.0

        for i in range(1, num_steps + 1):
            t = i / num_steps
            # Cubic Ease-Out: f(t) = 1 - (1 - t)^3
            eased_t = 1.0 - math.pow(1.0 - t, 3)

            base_x = target_dx * eased_t
            base_y = target_dy * eased_t
            
            step_time = duration_ms / num_steps
            total_time_ms += step_time

            noise_x = self.perlin_x.noise(noise_offset_x + total_time_ms * noise_speed * 0.01) * max_drift
            noise_y = self.perlin_y.noise(noise_offset_y + total_time_ms * noise_speed * 0.01) * max_drift
            
            # Fade out noise towards the end so it lands precisely
            noise_fade = 1.0 - t
            
            final_x = base_x + noise_x * noise_fade
            final_y = base_y + noise_y * noise_fade
            
            # Make sure the very last step hits the exact target
            if i == num_steps:
                final_x = target_dx
                final_y = target_dy

            step_dx = final_x - prev_x
            step_dy = final_y - prev_y

            yield RecoilData(
                dx=step_dx,
                dy=step_dy,
                delay=step_time
            )

            prev_x = final_x
            prev_y = final_y
