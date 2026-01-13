/**
 * LIC法（Line Integral Convolution）による鉛筆画生成
 * 論文: "LIC法を利用した鉛筆画の自動生成法" に基づく実装
 */

class LICPencilDrawing {
    constructor() {
        this.params = {
            kernelLength: 20,      // ストロークの長さ（畳み込みカーネルの長さ）
            brightness: 0.7,       // 明るさ係数 k
            edgeStrength: 0.5,     // エッジ強度
            paperStrength: 0.3,    // 紙テクスチャ強度
            strokeDirection: 'texture', // ストローク方向
            noiseScale: 1          // ノイズの粒度
        };
        this.progressCallback = null;
    }

    setParams(params) {
        Object.assign(this.params, params);
    }

    setProgressCallback(callback) {
        this.progressCallback = callback;
    }

    updateProgress(progress, text) {
        if (this.progressCallback) {
            this.progressCallback(progress, text);
        }
    }

    /**
     * メイン処理: 入力画像から鉛筆画を生成
     */
    async generate(inputImageData) {
        const width = inputImageData.width;
        const height = inputImageData.height;
        const inputData = inputImageData.data;

        // Step 1: グレースケール変換
        this.updateProgress(5, 'グレースケール変換中...');
        const grayscale = this.toGrayscale(inputData, width, height);
        await this.sleep(10);

        // Step 2: ホワイトノイズ生成（トーンにマッチ）
        this.updateProgress(15, 'ホワイトノイズ生成中...');
        const noise = this.generateToneMatchedNoise(grayscale, width, height);
        await this.sleep(10);

        // Step 3: ベクトル場生成（ストローク方向）
        this.updateProgress(25, 'ベクトル場生成中...');
        const vectorField = this.generateVectorField(grayscale, width, height);
        await this.sleep(10);

        // Step 4: LIC計算
        this.updateProgress(35, 'LIC計算中...');
        const licResult = await this.computeLIC(noise, vectorField, width, height);

        // Step 5: エッジ検出（Sobelオペレータ）
        this.updateProgress(80, 'エッジ検出中...');
        const edges = this.detectEdges(grayscale, width, height);
        await this.sleep(10);

        // Step 6: エッジを合成
        this.updateProgress(85, 'エッジ合成中...');
        const withEdges = this.blendEdges(licResult, edges, width, height);
        await this.sleep(10);

        // Step 7: 紙テクスチャを合成
        this.updateProgress(90, '紙テクスチャ合成中...');
        const paperTexture = this.generatePaperTexture(width, height);
        const final = this.blendPaperTexture(withEdges, paperTexture, width, height);
        await this.sleep(10);

        // Step 8: 出力ImageData作成
        this.updateProgress(95, '出力画像作成中...');
        const outputImageData = new ImageData(width, height);
        for (let i = 0; i < width * height; i++) {
            const val = Math.max(0, Math.min(255, final[i]));
            outputImageData.data[i * 4] = val;
            outputImageData.data[i * 4 + 1] = val;
            outputImageData.data[i * 4 + 2] = val;
            outputImageData.data[i * 4 + 3] = 255;
        }

        this.updateProgress(100, '完了');
        return outputImageData;
    }

    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * グレースケール変換
     */
    toGrayscale(data, width, height) {
        const grayscale = new Float32Array(width * height);
        for (let i = 0; i < width * height; i++) {
            const r = data[i * 4];
            const g = data[i * 4 + 1];
            const b = data[i * 4 + 2];
            // 標準的なグレースケール変換
            grayscale[i] = 0.299 * r + 0.587 * g + 0.114 * b;
        }
        return grayscale;
    }

    /**
     * トーンにマッチしたホワイトノイズ生成
     * 論文の式: P >= T の場合 255, それ以外 0
     * T = k * (1 - I_input / 255)
     */
    generateToneMatchedNoise(grayscale, width, height) {
        const noise = new Float32Array(width * height);
        const k = this.params.brightness;
        const scale = this.params.noiseScale;

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                // スケールを考慮したノイズ生成
                const sx = Math.floor(x / scale);
                const sy = Math.floor(y / scale);
                const seed = sx + sy * Math.ceil(width / scale);

                const i = y * width + x;
                const intensity = grayscale[i];
                const threshold = k * (1 - intensity / 255);

                // シード付き擬似乱数
                const random = this.seededRandom(seed + i * 0.1);

                if (random >= threshold) {
                    noise[i] = 255;
                } else {
                    noise[i] = 0;
                }
            }
        }
        return noise;
    }

    /**
     * シード付き擬似乱数生成
     */
    seededRandom(seed) {
        const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
        return x - Math.floor(x);
    }

    /**
     * ベクトル場生成（ストローク方向を決定）
     */
    generateVectorField(grayscale, width, height) {
        const vectorField = new Float32Array(width * height * 2);
        const direction = this.params.strokeDirection;

        if (direction === 'texture') {
            // フーリエ解析によるテクスチャ方向検出
            return this.detectTextureDirection(grayscale, width, height);
        }

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const i = (y * width + x) * 2;
                let angle;

                switch (direction) {
                    case 'horizontal':
                        angle = 0;
                        break;
                    case 'vertical':
                        angle = Math.PI / 2;
                        break;
                    case 'diagonal':
                        angle = Math.PI / 4;
                        break;
                    case 'random':
                        angle = this.seededRandom(x + y * width) * Math.PI;
                        break;
                    case 'crosshatch':
                        // クロスハッチング: 位置に応じて方向を変える
                        const region = Math.floor(x / 50) + Math.floor(y / 50);
                        angle = (region % 2 === 0) ? Math.PI / 4 : -Math.PI / 4;
                        break;
                    default:
                        angle = Math.PI / 4;
                }

                vectorField[i] = Math.cos(angle);
                vectorField[i + 1] = Math.sin(angle);
            }
        }
        return vectorField;
    }

    /**
     * テクスチャ方向検出（簡易版：勾配ベースの方向検出）
     * 論文のフーリエ解析の代わりに、勾配の垂直方向を使用
     */
    detectTextureDirection(grayscale, width, height) {
        const vectorField = new Float32Array(width * height * 2);
        const windowSize = 9;
        const half = Math.floor(windowSize / 2);

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const i = (y * width + x) * 2;

                // 局所領域での勾配計算
                let gx = 0, gy = 0;

                for (let wy = -half; wy <= half; wy++) {
                    for (let wx = -half; wx <= half; wx++) {
                        const nx = Math.min(Math.max(x + wx, 0), width - 1);
                        const ny = Math.min(Math.max(y + wy, 0), height - 1);
                        const nx2 = Math.min(Math.max(x + wx + 1, 0), width - 1);
                        const ny2 = Math.min(Math.max(y + wy + 1, 0), height - 1);

                        const val = grayscale[ny * width + nx];
                        const valX = grayscale[ny * width + nx2];
                        const valY = grayscale[ny2 * width + nx];

                        gx += valX - val;
                        gy += valY - val;
                    }
                }

                // 勾配の大きさ
                const mag = Math.sqrt(gx * gx + gy * gy);

                if (mag > 1) {
                    // 勾配に垂直な方向（テクスチャに沿った方向）
                    vectorField[i] = -gy / mag;
                    vectorField[i + 1] = gx / mag;
                } else {
                    // 勾配が小さい場合はデフォルトの斜め方向
                    const angle = Math.PI / 4;
                    vectorField[i] = Math.cos(angle);
                    vectorField[i + 1] = Math.sin(angle);
                }
            }
        }

        // ベクトル場を滑らかにする
        return this.smoothVectorField(vectorField, width, height);
    }

    /**
     * ベクトル場の平滑化
     */
    smoothVectorField(vectorField, width, height) {
        const smoothed = new Float32Array(width * height * 2);
        const kernelSize = 5;
        const half = Math.floor(kernelSize / 2);

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                let sumX = 0, sumY = 0, count = 0;

                for (let ky = -half; ky <= half; ky++) {
                    for (let kx = -half; kx <= half; kx++) {
                        const nx = x + kx;
                        const ny = y + ky;
                        if (nx >= 0 && nx < width && ny >= 0 && ny < height) {
                            const ni = (ny * width + nx) * 2;
                            sumX += vectorField[ni];
                            sumY += vectorField[ni + 1];
                            count++;
                        }
                    }
                }

                const i = (y * width + x) * 2;
                const mag = Math.sqrt(sumX * sumX + sumY * sumY);
                if (mag > 0) {
                    smoothed[i] = sumX / mag;
                    smoothed[i + 1] = sumY / mag;
                } else {
                    smoothed[i] = vectorField[i];
                    smoothed[i + 1] = vectorField[i + 1];
                }
            }
        }
        return smoothed;
    }

    /**
     * LIC計算（Line Integral Convolution）
     * 流線に沿ってローパスフィルタをかける
     */
    async computeLIC(noise, vectorField, width, height) {
        const result = new Float32Array(width * height);
        const L = this.params.kernelLength;
        const halfL = L / 2;

        // ボックスフィルタ（等しい重み）
        const kernel = new Float32Array(L);
        for (let i = 0; i < L; i++) {
            kernel[i] = 1.0 / L;
        }

        // 各ピクセルに対してLIC計算
        for (let y = 0; y < height; y++) {
            // 進捗更新
            if (y % 20 === 0) {
                const progress = 35 + (y / height) * 45;
                this.updateProgress(progress, `LIC計算中... ${Math.floor(y / height * 100)}%`);
                await this.sleep(0);
            }

            for (let x = 0; x < width; x++) {
                let sum = 0;
                let weightSum = 0;

                // 順方向の流線追跡
                let px = x, py = y;
                for (let k = 0; k < halfL; k++) {
                    const ix = Math.floor(px);
                    const iy = Math.floor(py);

                    if (ix < 0 || ix >= width || iy < 0 || iy >= height) break;

                    const ni = iy * width + ix;
                    const vi = ni * 2;

                    sum += noise[ni] * kernel[Math.floor(halfL) + k];
                    weightSum += kernel[Math.floor(halfL) + k];

                    // 次の位置へ（Euler積分）
                    px += vectorField[vi];
                    py += vectorField[vi + 1];
                }

                // 逆方向の流線追跡
                px = x;
                py = y;
                for (let k = 1; k < halfL; k++) {
                    const ix = Math.floor(px);
                    const iy = Math.floor(py);

                    if (ix < 0 || ix >= width || iy < 0 || iy >= height) break;

                    const ni = iy * width + ix;
                    const vi = ni * 2;

                    // 逆方向に進む
                    px -= vectorField[vi];
                    py -= vectorField[vi + 1];

                    const nix = Math.floor(px);
                    const niy = Math.floor(py);
                    if (nix < 0 || nix >= width || niy < 0 || niy >= height) break;

                    const nni = niy * width + nix;
                    sum += noise[nni] * kernel[Math.floor(halfL) - k];
                    weightSum += kernel[Math.floor(halfL) - k];
                }

                // 正規化
                const idx = y * width + x;
                if (weightSum > 0) {
                    result[idx] = sum / weightSum;
                } else {
                    result[idx] = noise[idx];
                }
            }
        }

        return result;
    }

    /**
     * Sobelオペレータによるエッジ検出
     */
    detectEdges(grayscale, width, height) {
        const edges = new Float32Array(width * height);

        // Sobelカーネル
        const sobelX = [-1, 0, 1, -2, 0, 2, -1, 0, 1];
        const sobelY = [-1, -2, -1, 0, 0, 0, 1, 2, 1];

        for (let y = 1; y < height - 1; y++) {
            for (let x = 1; x < width - 1; x++) {
                let gx = 0, gy = 0;

                for (let ky = -1; ky <= 1; ky++) {
                    for (let kx = -1; kx <= 1; kx++) {
                        const idx = (y + ky) * width + (x + kx);
                        const ki = (ky + 1) * 3 + (kx + 1);
                        const val = grayscale[idx];

                        gx += val * sobelX[ki];
                        gy += val * sobelY[ki];
                    }
                }

                const magnitude = Math.sqrt(gx * gx + gy * gy);
                edges[y * width + x] = Math.min(255, magnitude);
            }
        }

        return edges;
    }

    /**
     * エッジをLIC結果に合成
     */
    blendEdges(licResult, edges, width, height) {
        const result = new Float32Array(width * height);
        const strength = this.params.edgeStrength;

        for (let i = 0; i < width * height; i++) {
            // エッジを暗くする（鉛筆の輪郭線として）
            const edgeVal = edges[i] * strength;
            result[i] = Math.max(0, licResult[i] - edgeVal);
        }

        return result;
    }

    /**
     * 紙テクスチャ生成（パーリンノイズ風）
     */
    generatePaperTexture(width, height) {
        const texture = new Float32Array(width * height);

        // 複数スケールのノイズを重ね合わせ
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                let val = 128; // 基準値

                // 粗いノイズ
                val += (this.seededRandom(Math.floor(x / 8) + Math.floor(y / 8) * 1000) - 0.5) * 30;

                // 細かいノイズ
                val += (this.seededRandom(x + y * width + 10000) - 0.5) * 20;

                // 中間スケールのノイズ
                val += (this.seededRandom(Math.floor(x / 3) + Math.floor(y / 3) * 500 + 5000) - 0.5) * 15;

                texture[y * width + x] = val;
            }
        }

        return texture;
    }

    /**
     * 紙テクスチャを合成
     * 論文: LIC画像から紙のサンプルの差分を取る
     */
    blendPaperTexture(image, paperTexture, width, height) {
        const result = new Float32Array(width * height);
        const strength = this.params.paperStrength;

        for (let i = 0; i < width * height; i++) {
            // 紙テクスチャの凹凸による顔料の付着量変化をシミュレート
            const paperEffect = (paperTexture[i] - 128) * strength;
            result[i] = image[i] - paperEffect;

            // 明るさ補正
            result[i] = Math.max(0, Math.min(255, result[i]));
        }

        return result;
    }
}

// グローバルに公開
window.LICPencilDrawing = LICPencilDrawing;
