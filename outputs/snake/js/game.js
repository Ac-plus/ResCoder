// 贪吃蛇游戏主逻辑
class SnakeGame {
    constructor() {
        this.canvas = document.getElementById('game-canvas');
        this.ctx = this.canvas.getContext('2d');
        
        // 游戏状态
        this.gameRunning = false;
        this.gamePaused = false;
        this.gameOver = false;
        
        // 游戏参数
        this.gridSize = 20;
        this.snake = [];
        this.food = {};
        this.direction = 'right';
        this.nextDirection = 'right';
        this.score = 0;
        this.highScore = localStorage.getItem('snakeHighScore') || 0;
        this.speed = 150; // 毫秒
        this.speedLevel = 'normal';
        this.foodEaten = 0;
        
        // DOM元素
        this.scoreElement = document.getElementById('score');
        this.highScoreElement = document.getElementById('high-score');
        this.speedElement = document.getElementById('speed');
        this.finalScoreElement = document.getElementById('final-score');
        this.gameOverElement = document.getElementById('game-over');
        this.welcomeElement = document.getElementById('welcome');
        
        // 按钮元素
        this.startBtn = document.getElementById('start-btn');
        this.pauseBtn = document.getElementById('pause-btn');
        this.resetBtn = document.getElementById('reset-btn');
        this.restartBtn = document.getElementById('restart-btn');
        
        // 速度控制按钮
        this.speedSlowBtn = document.getElementById('speed-slow');
        this.speedNormalBtn = document.getElementById('speed-normal');
        this.speedFastBtn = document.getElementById('speed-fast');
        
        // 初始化
        this.init();
        this.setupEventListeners();
        this.updateHighScoreDisplay();
    }
    
    init() {
        // 初始化蛇 - 长度为3
        this.snake = [
            {x: 5, y: 10},
            {x: 4, y: 10},
            {x: 3, y: 10}
        ];
        
        // 生成第一个食物
        this.generateFood();
        
        // 重置游戏状态
        this.score = 0;
        this.foodEaten = 0;
        this.direction = 'right';
        this.nextDirection = 'right';
        this.gameOver = false;
        this.gamePaused = false;
        
        // 更新显示
        this.updateScoreDisplay();
        this.updateSpeedDisplay();
        
        // 绘制初始状态
        this.draw();
        
        // 显示欢迎界面
        this.welcomeElement.classList.remove('hidden');
        this.gameOverElement.classList.add('hidden');
    }
    
    setupEventListeners() {
        // 键盘控制
        document.addEventListener('keydown', (e) => this.handleKeyPress(e));
        
        // 游戏控制按钮
        this.startBtn.addEventListener('click', () => this.startGame());
        this.pauseBtn.addEventListener('click', () => this.togglePause());
        this.resetBtn.addEventListener('click', () => this.resetGame());
        this.restartBtn.addEventListener('click', () => this.resetGame());
        
        // 速度控制按钮
        this.speedSlowBtn.addEventListener('click', () => this.setSpeed('slow'));
        this.speedNormalBtn.addEventListener('click', () => this.setSpeed('normal'));
        this.speedFastBtn.addEventListener('click', () => this.setSpeed('fast'));
        
        // 空格键暂停/继续
        document.addEventListener('keydown', (e) => {
            if (e.code === 'Space') {
                e.preventDefault();
                this.togglePause();
            }
            if (e.code === 'KeyR') {
                this.resetGame();
            }
            if (e.code === 'Escape') {
                this.resetGame();
            }
        });
    }
    
    handleKeyPress(e) {
        if (!this.gameRunning || this.gamePaused) return;
        
        switch(e.key) {
            case 'ArrowUp':
                if (this.direction !== 'down') this.nextDirection = 'up';
                break;
            case 'ArrowDown':
                if (this.direction !== 'up') this.nextDirection = 'down';
                break;
            case 'ArrowLeft':
                if (this.direction !== 'right') this.nextDirection = 'left';
                break;
            case 'ArrowRight':
                if (this.direction !== 'left') this.nextDirection = 'right';
                break;
        }
    }
    
    startGame() {
        if (this.gameRunning && !this.gamePaused) return;
        
        this.gameRunning = true;
        this.gamePaused = false;
        this.welcomeElement.classList.add('hidden');
        this.gameOverElement.classList.add('hidden');
        
        this.startBtn.innerHTML = '<i class="fas fa-play"></i> 继续游戏';
        this.pauseBtn.disabled = false;
        
        this.gameLoop();
    }
    
    togglePause() {
        if (!this.gameRunning) return;
        
        this.gamePaused = !this.gamePaused;
        
        if (this.gamePaused) {
            this.pauseBtn.innerHTML = '<i class="fas fa-play"></i> 继续';
            this.startBtn.innerHTML = '<i class="fas fa-play"></i> 继续游戏';
        } else {
            this.pauseBtn.innerHTML = '<i class="fas fa-pause"></i> 暂停';
            this.gameLoop();
        }
    }
    
    resetGame() {
        this.gameRunning = false;
        this.gamePaused = false;
        this.init();
        
        this.startBtn.innerHTML = '<i class="fas fa-play"></i> 开始游戏';
        this.pauseBtn.innerHTML = '<i class="fas fa-pause"></i> 暂停';
        this.pauseBtn.disabled = true;
    }
    
    setSpeed(level) {
        this.speedLevel = level;
        
        // 更新按钮状态
        [this.speedSlowBtn, this.speedNormalBtn, this.speedFastBtn].forEach(btn => {
            btn.classList.remove('active');
        });
        
        switch(level) {
            case 'slow':
                this.speed = 200;
                this.speedSlowBtn.classList.add('active');
                break;
            case 'normal':
                this.speed = 150;
                this.speedNormalBtn.classList.add('active');
                break;
            case 'fast':
                this.speed = 100;
                this.speedFastBtn.classList.add('active');
                break;
        }
        
        this.updateSpeedDisplay();
    }
    
    gameLoop() {
        if (!this.gameRunning || this.gamePaused || this.gameOver) return;
        
        this.update();
        this.draw();
        
        setTimeout(() => this.gameLoop(), this.speed);
    }
    
    update() {
        // 更新方向
        this.direction = this.nextDirection;
        
        // 计算新的头部位置
        const head = {...this.snake[0]};
        
        switch(this.direction) {
            case 'up':
                head.y -= 1;
                break;
            case 'down':
                head.y += 1;
                break;
            case 'left':
                head.x -= 1;
                break;
            case 'right':
                head.x += 1;
                break;
        }
        
        // 检查碰撞
        if (this.checkCollision(head)) {
            this.endGame();
            return;
        }
        
        // 添加新的头部
        this.snake.unshift(head);
        
        // 检查是否吃到食物
        if (head.x === this.food.x && head.y === this.food.y) {
            this.score += 10;
            this.foodEaten++;
            
            // 每吃5个食物加速一次
            if (this.foodEaten % 5 === 0) {
                this.increaseSpeed();
            }
            
            this.updateScoreDisplay();
            this.generateFood();
        } else {
            // 如果没有吃到食物，移除尾部
            this.snake.pop();
        }
    }
    
    checkCollision(head) {
        // 检查墙壁碰撞
        if (head.x < 0 || head.x >= this.canvas.width / this.gridSize ||
            head.y < 0 || head.y >= this.canvas.height / this.gridSize) {
            return true;
        }
        
        // 检查自身碰撞
        for (let segment of this.snake) {
            if (head.x === segment.x && head.y === segment.y) {
                return true;
            }
        }
        
        return false;
    }
    
    generateFood() {
        let food;
        let foodOnSnake;
        
        do {
            foodOnSnake = false;
            food = {
                x: Math.floor(Math.random() * (this.canvas.width / this.gridSize)),
                y: Math.floor(Math.random() * (this.canvas.height / this.gridSize))
            };
            
            // 检查食物是否在蛇身上
            for (let segment of this.snake) {
                if (food.x === segment.x && food.y === segment.y) {
                    foodOnSnake = true;
                    break;
                }
            }
        } while (foodOnSnake);
        
        this.food = food;
    }
    
    increaseSpeed() {
        if (this.speed > 50) {
            this.speed -= 10;
            this.updateSpeedDisplay();
        }
    }
    
    draw() {
        // 清空画布
        this.ctx.fillStyle = '#0a0a1a';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 绘制网格
        this.drawGrid();
        
        // 绘制蛇
        this.drawSnake();
        
        // 绘制食物
        this.drawFood();
    }
    
    drawGrid() {
        this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
        this.ctx.lineWidth = 1;
        
        // 绘制垂直线
        for (let x = 0; x <= this.canvas.width; x += this.gridSize) {
            this.ctx.beginPath();
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, this.canvas.height);
            this.ctx.stroke();
        }
        
        // 绘制水平线
        for (let y = 0; y <= this.canvas.height; y += this.gridSize) {
            this.ctx.beginPath();
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(this.canvas.width, y);
            this.ctx.stroke();
        }
    }
    
    drawSnake() {
        // 绘制蛇身
        for (let i = 0; i < this.snake.length; i++) {
            const segment = this.snake[i];
            
            // 蛇头
            if (i === 0) {
                this.ctx.fillStyle = '#00dbde';
                this.ctx.fillRect(
                    segment.x * this.gridSize,
                    segment.y * this.gridSize,
                    this.gridSize,
                    this.gridSize
                );
                
                // 蛇头眼睛
                this.ctx.fillStyle = '#ffffff';
                const eyeSize = this.gridSize / 5;
                
                // 根据方向绘制眼睛
                let leftEyeX, leftEyeY, rightEyeX, rightEyeY;
                
                switch(this.direction) {
                    case 'right':
                        leftEyeX = segment.x * this.gridSize + this.gridSize - eyeSize * 2;
                        leftEyeY = segment.y * this.gridSize + eyeSize * 2;
                        rightEyeX = segment.x * this.gridSize + this.gridSize - eyeSize * 2;
                        rightEyeY = segment.y * this.gridSize + this.gridSize - eyeSize * 3;
                        break;
                    case 'left':
                        leftEyeX = segment.x * this.gridSize + eyeSize;
                        leftEyeY = segment.y * this.gridSize + eyeSize * 2;
                        rightEyeX = segment.x * this.gridSize + eyeSize;
                        rightEyeY = segment.y * this.gridSize + this.gridSize - eyeSize * 3;
                        break;
                    case 'up':
                        leftEyeX = segment.x * this.gridSize + eyeSize * 2;
                        leftEyeY = segment.y * this.gridSize + eyeSize;
                        rightEyeX = segment.x * this.gridSize + this.gridSize - eyeSize * 3;
                        rightEyeY = segment.y * this.gridSize + eyeSize;
                        break;
                    case 'down':
                        leftEyeX = segment.x * this.gridSize + eyeSize * 2;
                        leftEyeY = segment.y * this.gridSize + this.gridSize - eyeSize * 2;
                        rightEyeX = segment.x * this.gridSize + this.gridSize - eyeSize * 3;
                        rightEyeY = segment.y * this.gridSize + this.gridSize - eyeSize * 2;
                        break;
                }
                
                this.ctx.fillRect(leftEyeX, leftEyeY, eyeSize, eyeSize);
                this.ctx.fillRect(rightEyeX, rightEyeY, eyeSize, eyeSize);
            } 
            // 蛇身
            else {
                // 渐变颜色效果
                const colorValue = Math.max(100, 255 - i * 20);
                this.ctx.fillStyle = `rgb(0, ${colorValue}, ${colorValue})`;
                
                this.ctx.fillRect(
                    segment.x * this.gridSize,
                    segment.y * this.gridSize,
                    this.gridSize,
                    this.gridSize
                );
                
                // 蛇身内部装饰
                this.ctx.fillStyle = `rgba(255, 255, 255, 0.3)`;
                const innerSize = this.gridSize / 3;
                this.ctx.fillRect(
                    segment.x * this.gridSize + innerSize,
                    segment.y * this.gridSize + innerSize,
                    innerSize,
                    innerSize
                );
            }
            
            // 蛇身边框
            this.ctx.strokeStyle = '#0093e9';
            this.ctx.lineWidth = 1;
            this.ctx.strokeRect(
                segment.x * this.gridSize,
                segment.y * this.gridSize,
                this.gridSize,
                this.gridSize
            );
        }
    }
    
    drawFood() {
        // 绘制食物（苹果）
        const x = this.food.x * this.gridSize;
        const y = this.food.y * this.gridSize;
        const size = this.gridSize;
        
        // 苹果主体
        this.ctx.fillStyle = '#ff4757';
        this.ctx.beginPath();
        this.ctx.ellipse(
            x + size/2,
            y + size/2,
            size/2.5,
            size/2.2,
            0,
            0,
            Math.PI * 2
        );
        this.ctx.fill();
        
        // 苹果茎
        this.ctx.fillStyle = '#2ed573';
        this.ctx.fillRect(
            x + size/2 - 1,
            y + 2,
            2,
            size/4
        );
        
        // 苹果高光
        this.ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
        this.ctx.beginPath();
        this.ctx.ellipse(
            x + size/3,
            y + size/3,
            size/8,
            size/6,
            0,
            0,
            Math.PI * 2
        );
        this.ctx.fill();
        
        // 食物发光效果
        this.ctx.shadowColor = '#ff4757';
        this.ctx.shadowBlur = 10;
        this.ctx.beginPath();
        this.ctx.ellipse(
            x + size/2,
            y + size/2,
            size/2.5,
            size/2.2,
            0,
            0,
            Math.PI * 2
        );
        this.ctx.strokeStyle = 'rgba(255, 71, 87, 0.5)';
        this.ctx.lineWidth = 2;
        this.ctx.stroke();
        this.ctx.shadowBlur = 0;
    }
    
    endGame() {
        this.gameRunning = false;
        this.gameOver = true;
        
        // 更新最高分
        if (this.score > this.highScore) {
            this.highScore = this.score;
            localStorage.setItem('snakeHighScore', this.highScore);
            this.updateHighScoreDisplay();
        }
        
        // 显示游戏结束界面
        this.finalScoreElement.textContent = this.score;
        this.gameOverElement.classList.remove('hidden');
        
        // 添加脉冲动画
        this.gameOverElement.classList.add('pulse');
        setTimeout(() => {
            this.gameOverElement.classList.remove('pulse');
        }, 500);
    }
    
    updateScoreDisplay() {
        this.scoreElement.textContent = this.score;
        this.scoreElement.classList.add('pulse');
        setTimeout(() => {
            this.scoreElement.classList.remove('pulse');
        }, 300);
    }
    
    updateHighScoreDisplay() {
        this.highScoreElement.textContent = this.highScore;
    }
    
    updateSpeedDisplay() {
        let speedText;
        if (this.speed >= 180) speedText = '慢速';
        else if (this.speed >= 120) speedText = '正常';
        else if (this.speed >= 80) speedText = '快速';
        else speedText = '极速';
        
        this.speedElement.textContent = speedText;
    }
}

// 页面加载完成后初始化游戏
document.addEventListener('DOMContentLoaded', () => {
    const game = new SnakeGame();
    
    // 全局访问（用于调试）
    window.snakeGame = game;
});