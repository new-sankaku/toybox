/**
 * アプリケーションメインスクリプト
 * UIとLIC処理を接続
 */

document.addEventListener('DOMContentLoaded', () => {
    // DOM要素
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const controls = document.getElementById('controls');
    const canvasContainer = document.getElementById('canvasContainer');
    const inputCanvas = document.getElementById('inputCanvas');
    const outputCanvas = document.getElementById('outputCanvas');
    const generateBtn = document.getElementById('generateBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const progressContainer = document.getElementById('progressContainer');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');

    // パラメータ入力
    const kernelLengthInput = document.getElementById('kernelLength');
    const brightnessInput = document.getElementById('brightness');
    const edgeStrengthInput = document.getElementById('edgeStrength');
    const paperStrengthInput = document.getElementById('paperStrength');
    const strokeDirectionInput = document.getElementById('strokeDirection');
    const noiseScaleInput = document.getElementById('noiseScale');

    // 値表示
    const kernelLengthValue = document.getElementById('kernelLengthValue');
    const brightnessValue = document.getElementById('brightnessValue');
    const edgeStrengthValue = document.getElementById('edgeStrengthValue');
    const paperStrengthValue = document.getElementById('paperStrengthValue');
    const noiseScaleValue = document.getElementById('noiseScaleValue');

    // コンテキスト
    const inputCtx = inputCanvas.getContext('2d');
    const outputCtx = outputCanvas.getContext('2d');

    // LICインスタンス
    const licProcessor = new LICPencilDrawing();

    // 現在の画像
    let currentImage = null;

    // パラメータ表示の更新
    function updateParamDisplay() {
        kernelLengthValue.textContent = kernelLengthInput.value;
        brightnessValue.textContent = brightnessInput.value;
        edgeStrengthValue.textContent = edgeStrengthInput.value;
        paperStrengthValue.textContent = paperStrengthInput.value;
        noiseScaleValue.textContent = noiseScaleInput.value;
    }

    // パラメータ入力のイベントリスナー
    [kernelLengthInput, brightnessInput, edgeStrengthInput, paperStrengthInput, noiseScaleInput].forEach(input => {
        input.addEventListener('input', updateParamDisplay);
    });

    // ドロップゾーンのイベント
    dropZone.addEventListener('click', () => fileInput.click());

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');

        const files = e.dataTransfer.files;
        if (files.length > 0 && files[0].type.startsWith('image/')) {
            loadImage(files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            loadImage(e.target.files[0]);
        }
    });

    /**
     * 画像の読み込み
     */
    function loadImage(file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                // 最大サイズを制限（処理時間のため）
                const maxSize = 800;
                let width = img.width;
                let height = img.height;

                if (width > maxSize || height > maxSize) {
                    if (width > height) {
                        height = Math.round(height * maxSize / width);
                        width = maxSize;
                    } else {
                        width = Math.round(width * maxSize / height);
                        height = maxSize;
                    }
                }

                // キャンバスサイズ設定
                inputCanvas.width = width;
                inputCanvas.height = height;
                outputCanvas.width = width;
                outputCanvas.height = height;

                // 入力画像を描画
                inputCtx.drawImage(img, 0, 0, width, height);

                currentImage = img;
                canvasContainer.classList.add('visible');
                generateBtn.disabled = false;
                downloadBtn.disabled = true;

                // 出力キャンバスをクリア
                outputCtx.fillStyle = '#f0f0f0';
                outputCtx.fillRect(0, 0, width, height);
                outputCtx.fillStyle = '#999';
                outputCtx.font = '16px sans-serif';
                outputCtx.textAlign = 'center';
                outputCtx.fillText('「鉛筆画を生成」をクリック', width / 2, height / 2);
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    }

    /**
     * 進捗表示の更新
     */
    function updateProgress(percent, text) {
        progressFill.style.width = `${percent}%`;
        progressText.textContent = text;
    }

    /**
     * 鉛筆画生成
     */
    async function generatePencilDrawing() {
        if (!currentImage) return;

        // UI更新
        generateBtn.disabled = true;
        downloadBtn.disabled = true;
        progressContainer.classList.add('visible');
        updateProgress(0, '処理開始...');

        // パラメータ設定
        licProcessor.setParams({
            kernelLength: parseInt(kernelLengthInput.value),
            brightness: parseFloat(brightnessInput.value),
            edgeStrength: parseFloat(edgeStrengthInput.value),
            paperStrength: parseFloat(paperStrengthInput.value),
            strokeDirection: strokeDirectionInput.value,
            noiseScale: parseInt(noiseScaleInput.value)
        });

        // 進捗コールバック
        licProcessor.setProgressCallback(updateProgress);

        try {
            // 入力画像データ取得
            const inputImageData = inputCtx.getImageData(
                0, 0, inputCanvas.width, inputCanvas.height
            );

            // LIC処理実行
            const outputImageData = await licProcessor.generate(inputImageData);

            // 結果を出力キャンバスに描画
            outputCtx.putImageData(outputImageData, 0, 0);

            // クロスハッチングの場合は2回目のパスを重ねる
            if (strokeDirectionInput.value === 'crosshatch') {
                await applyCrosshatchSecondPass(inputImageData);
            }

            downloadBtn.disabled = false;
        } catch (error) {
            console.error('Error generating pencil drawing:', error);
            alert('処理中にエラーが発生しました: ' + error.message);
        } finally {
            generateBtn.disabled = false;
            setTimeout(() => {
                progressContainer.classList.remove('visible');
            }, 1000);
        }
    }

    /**
     * クロスハッチングの2パス目
     */
    async function applyCrosshatchSecondPass(inputImageData) {
        // 一時的に方向を変更
        const tempProcessor = new LICPencilDrawing();
        tempProcessor.setParams({
            kernelLength: parseInt(kernelLengthInput.value),
            brightness: parseFloat(brightnessInput.value) * 0.5, // 2パス目は薄く
            edgeStrength: 0, // エッジは1回目で適用済み
            paperStrength: 0, // 紙テクスチャも1回目で適用済み
            strokeDirection: 'diagonal', // 別の斜め方向
            noiseScale: parseInt(noiseScaleInput.value)
        });

        // ベクトル場を反対斜めに
        const secondPass = await tempProcessor.generate(inputImageData);

        // 現在の出力と合成（乗算ブレンド）
        const currentOutput = outputCtx.getImageData(0, 0, outputCanvas.width, outputCanvas.height);

        for (let i = 0; i < currentOutput.data.length; i += 4) {
            // 乗算ブレンド
            const v1 = currentOutput.data[i] / 255;
            const v2 = secondPass.data[i] / 255;
            const blended = Math.floor(v1 * v2 * 255);

            currentOutput.data[i] = blended;
            currentOutput.data[i + 1] = blended;
            currentOutput.data[i + 2] = blended;
        }

        outputCtx.putImageData(currentOutput, 0, 0);
    }

    /**
     * 画像ダウンロード
     */
    function downloadImage() {
        const link = document.createElement('a');
        link.download = 'pencil-drawing.png';
        link.href = outputCanvas.toDataURL('image/png');
        link.click();
    }

    // ボタンイベント
    generateBtn.addEventListener('click', generatePencilDrawing);
    downloadBtn.addEventListener('click', downloadImage);

    // 初期表示
    updateParamDisplay();
});
