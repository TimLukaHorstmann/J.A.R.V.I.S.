class JarvisVisualizer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.particles = [];
        // Reduce particles on mobile for performance
        this.numParticles = window.innerWidth < 768 ? 80 : 200;
        this.radius = window.innerWidth < 768 ? 150 : 250;
        this.baseRadius = this.radius;
        this.centerX = 0;
        this.centerY = 0;
        this.angleX = 0;
        this.angleY = 0;
        this.isSpeaking = false;
        this.amplitude = 0;
        this.targetAmplitude = 0;

        // Load House Hologram Image
        this.houseImage = new Image();
        this.houseImage.src = 'assets/images/house_hologram3.png';
        this.houseImageLoaded = false;
        this.houseImage.onload = () => {
            this.houseImageLoaded = true;
        };
        
        this.resize();
        this.initParticles();
        
        window.addEventListener('resize', () => this.resize());
        this.animate();
    }

    resize() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
        this.centerX = this.canvas.width / 2;
        this.centerY = this.canvas.height / 2;
    }

    initParticles() {
        for (let i = 0; i < this.numParticles; i++) {
            // Distribute points on a sphere using Fibonacci sphere algorithm
            const y = 1 - (i / (this.numParticles - 1)) * 2;
            const radiusAtY = Math.sqrt(1 - y * y);
            const theta = i * Math.PI * (3 - Math.sqrt(5)); // Golden angle

            const x = Math.cos(theta) * radiusAtY;
            const z = Math.sin(theta) * radiusAtY;

            this.particles.push({
                x: x * this.radius,
                y: y * this.radius,
                z: z * this.radius,
                baseX: x,
                baseY: y,
                baseZ: z,
                size: Math.random() * 2 + 1
            });
        }
    }

    setSpeaking(speaking) {
        this.isSpeaking = speaking;
    }

    update() {
        // Smooth amplitude transition
        if (this.isSpeaking) {
            this.targetAmplitude = 1.0;
        } else {
            this.targetAmplitude = 0.0;
        }
        this.amplitude += (this.targetAmplitude - this.amplitude) * 0.05; // Slower transition

        // Rotate - Slower, more mystical
        this.angleY += 0.002 + (this.amplitude * 0.005);
        this.angleX += 0.001 + (this.amplitude * 0.002);

        // Pulse radius - Gentle breathing
        const pulse = Math.sin(Date.now() * 0.002) * 5 + (Math.sin(Date.now() * 0.01) * 8 * this.amplitude);
        this.radius = this.baseRadius + pulse;

        // Update particles
        this.particles.forEach(p => {
            // Rotate
            let x = p.baseX * this.radius;
            let y = p.baseY * this.radius;
            let z = p.baseZ * this.radius;

            // Add very subtle noise/jitter when speaking (reduced significantly)
            if (this.amplitude > 0.1) {
                x += (Math.random() - 0.5) * 2 * this.amplitude;
                y += (Math.random() - 0.5) * 2 * this.amplitude;
                z += (Math.random() - 0.5) * 2 * this.amplitude;
            }

            // Rotation Matrix Y
            let x1 = x * Math.cos(this.angleY) - z * Math.sin(this.angleY);
            let z1 = z * Math.cos(this.angleY) + x * Math.sin(this.angleY);

            // Rotation Matrix X
            let y2 = y * Math.cos(this.angleX) - z1 * Math.sin(this.angleX);
            let z2 = z1 * Math.cos(this.angleX) + y * Math.sin(this.angleX);

            p.x = x1 + this.centerX;
            p.y = y2 + this.centerY;
            p.z = z2;
            p.scale = (400 / (400 + z2)); // Perspective projection
        });
    }

    draw() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Draw House Hologram
        if (this.houseImageLoaded) {
            this.ctx.save();
            
            // Scale image based on current sphere radius to make it "breathe" with the sphere
            // The image should fit inside the sphere. 
            // Original dimensions: 2135 x 1489 (Landscape)
            const aspectRatio = 2135 / 1489;
            
            // Calculate dimensions to fit nicely inside the sphere
            // We use the radius as a baseline. 
            const drawWidth = this.radius * 1.8; 
            const drawHeight = drawWidth / aspectRatio;
            
            const x = this.centerX - drawWidth / 2;
            const y = this.centerY - drawHeight / 2;

            // Holographic effect
            this.ctx.globalAlpha = 0.8 + (this.amplitude * 0.2); // Pulse opacity with voice
            this.ctx.shadowBlur = 20;
            this.ctx.shadowColor = "rgba(0, 243, 255, 0.6)";
            
            // Draw the image
            this.ctx.drawImage(this.houseImage, x, y, drawWidth, drawHeight);
            
            this.ctx.restore();
        }
        
        // Draw connections
        this.ctx.strokeStyle = `rgba(0, 243, 255, ${0.1 + (this.amplitude * 0.2)})`;
        this.ctx.lineWidth = 0.5;
        this.ctx.beginPath();
        for (let i = 0; i < this.particles.length; i++) {
            const p1 = this.particles[i];
            for (let j = i + 1; j < this.particles.length; j++) {
                const p2 = this.particles[j];
                const dx = p1.x - p2.x;
                const dy = p1.y - p2.y;
                const dz = p1.z - p2.z;
                const dist = Math.sqrt(dx*dx + dy*dy + dz*dz);

                if (dist < 60) {
                    this.ctx.moveTo(p1.x, p1.y);
                    this.ctx.lineTo(p2.x, p2.y);
                }
            }
        }
        this.ctx.stroke();

        // Draw particles
        this.particles.forEach(p => {
            const alpha = (p.z + this.radius) / (2 * this.radius); // Fade back particles
            this.ctx.fillStyle = `rgba(0, 243, 255, ${alpha})`;
            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.size * p.scale, 0, Math.PI * 2);
            this.ctx.fill();
        });
    }

    animate() {
        this.update();
        this.draw();
        requestAnimationFrame(() => this.animate());
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.jarvisVisualizer = new JarvisVisualizer('jarvis-canvas');
});
