import os
import subprocess
import tempfile
import shutil
import threading
import uuid
from flask import Flask, request, render_template_string, send_file, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Render gratuit a peu de RAM, attention aux trop gros fichiers
app.config['MAX_CONTENT_LENGTH'] = 5000 * 1024 * 1024 

JOBS = {}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Convertisseur Vidéo En Ligne</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #121212; color: #fff; padding: 1rem; display: flex; justify-content: center; }
        .container { background: #1e1e1e; padding: 1.5rem; border-radius: 12px; box-shadow: 0 8px 16px rgba(0,0,0,0.5); max-width: 500px; width: 100%; }
        h1 { font-size: 1.5rem; color: #00e676; text-align: center; margin-bottom: 5px; }
        p.subtitle { text-align: center; color: #aaa; margin-bottom: 20px; font-size: 0.85rem; }
        .form-group { margin-bottom: 1.2rem; }
        label { display: block; margin-bottom: 6px; font-weight: bold; color: #ddd; font-size: 0.9rem; }
        select, input[type="file"] { width: 100%; padding: 10px; border: 1px solid #333; border-radius: 6px; background: #2a2a2a; color: #fff; box-sizing: border-box; }
        button { width: 100%; background: #00e676; color: #000; border: none; padding: 12px; font-size: 1.05rem; font-weight: bold; border-radius: 6px; cursor: pointer; transition: background 0.3s; }
        button:hover { background: #00c853; }
        button:disabled { background: #555; color: #888; cursor: not-allowed; }
        
        #progress-container { display: none; margin-top: 20px; }
        .progress-bg { background: #2a2a2a; border-radius: 10px; width: 100%; height: 18px; overflow: hidden; border: 1px solid #444; }
        .progress-bar { background: #00e676; height: 100%; width: 0%; transition: width 0.5s ease; }
        #status-text { text-align: center; margin-top: 8px; font-size: 0.85rem; color: #bbb; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Convertisseur Vidéo</h1>
        <p class="subtitle">TS, MP4, M3U8 avec choix de qualité</p>
        
        <form id="convertForm">
            <div class="form-group">
                <label>Type de conversion :</label>
                <select name="conversion_type" id="conversion_type" onchange="updateFileAccept()">
                    <option value="ts_to_mp4">Fusionner plusieurs TS ➔ 1 MP4</option>
                    <option value="mp4_to_ts">Convertir 1 MP4 ➔ 1 TS</option>
                    <option value="mp4_to_m3u8">Convertir 1 MP4 ➔ M3U8 (Dossier ZIP)</option>
                </select>
            </div>
            
            <div class="form-group">
                <label>Qualité Vidéo :</label>
                <select name="quality">
                    <option value="original">Originale (Ultra Rapide / Sans perte)</option>
                    <option value="1080p">Haute (1080p)</option>
                    <option value="720p">Moyenne (720p)</option>
                    <option value="480p">Basse (480p)</option>
                </select>
            </div>

            <div class="form-group">
                <label>Sélectionnez vos fichiers :</label>
                <input type="file" name="files" id="fileInput" multiple accept=".ts" required>
            </div>
            
            <button type="submit" id="submitBtn">Lancer la conversion</button>
        </form>

        <div id="progress-container">
            <div class="progress-bg">
                <div class="progress-bar" id="progressBar"></div>
            </div>
            <div id="status-text">Upload en cours...</div>
        </div>
    </div>

    <script>
        function updateFileAccept() {
            const type = document.getElementById('conversion_type').value;
            const input = document.getElementById('fileInput');
            if(type === 'ts_to_mp4') {
                input.accept = '.ts';
                input.multiple = true;
            } else {
                input.accept = '.mp4';
                input.multiple = false;
            }
        }

        document.getElementById('convertForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            const formData = new FormData(form);
            const btn = document.getElementById('submitBtn');
            const progressContainer = document.getElementById('progress-container');
            const progressBar = document.getElementById('progressBar');
            const statusText = document.getElementById('status-text');

            btn.disabled = true;
            progressContainer.style.display = 'block';
            progressBar.style.width = '20%';
            statusText.innerText = "Traitement des fichiers...";

            try {
                const response = await fetch('/start', { method: 'POST', body: formData });
                if (!response.ok) throw new Error(await response.text());
                
                const data = await response.json();
                const jobId = data.job_id;

                const interval = setInterval(async () => {
                    const statusRes = await fetch(`/status/${jobId}`);
                    const statusData = await statusRes.json();

                    if (statusData.status === 'processing') {
                        progressBar.style.width = '60%';
                        statusText.innerText = "Conversion FFmpeg en cours...";
                    } else if (statusData.status === 'zipping') {
                        progressBar.style.width = '85%';
                        statusText.innerText = "Création du fichier ZIP...";
                    } else if (statusData.status === 'done') {
                        clearInterval(interval);
                        progressBar.style.width = '100%';
                        statusText.innerText = "Terminé ! Téléchargement en cours...";
                        btn.disabled = false;
                        window.location.href = `/download/${jobId}`;
                    } else if (statusData.status === 'error') {
                        clearInterval(interval);
                        progressBar.style.width = '100%';
                        progressBar.style.backgroundColor = '#f44336';
                        statusText.innerText = "Erreur: " + statusData.error;
                        btn.disabled = false;
                    }
                }, 2000);

            } catch (err) {
                statusText.innerText = "Erreur : " + err.message;
                progressBar.style.backgroundColor = '#f44336';
                btn.disabled = false;
            }
        });
    </script>
</body>
</html>
"""

def process_video(job_id, temp_dir, filenames, conversion_type, quality):
    try:
        JOBS[job_id]['status'] = 'processing'
        
        quality_settings = []
        if quality == '1080p':
            quality_settings = ['-vf', 'scale=-2:1080', '-b:v', '3000k']
        elif quality == '720p':
            quality_settings = ['-vf', 'scale=-2:720', '-b:v', '1500k']
        elif quality == '480p':
            quality_settings = ['-vf', 'scale=-2:480', '-b:v', '800k']

        final_file = None

        if conversion_type == 'ts_to_mp4':
            filenames.sort()
            list_file_path = os.path.join(temp_dir, 'list.txt')
            with open(list_file_path, 'w', encoding='utf-8') as f:
                for fname in filenames:
                    f.write(f"file '{os.path.join(temp_dir, fname)}'\n")
            
            output_path = os.path.join(temp_dir, 'video_fusionnee.mp4')
            cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file_path]
            if quality == 'original':
                cmd.extend(['-c', 'copy'])
            else:
                cmd.extend(['-c:v', 'libx264', '-preset', 'fast'] + quality_settings + ['-c:a', 'aac', '-b:a', '128k'])
            cmd.append(output_path)
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            final_file = output_path

        elif conversion_type == 'mp4_to_ts':
            input_file = os.path.join(temp_dir, filenames[0])
            output_path = os.path.join(temp_dir, 'video_convertie.ts')
            cmd = ['ffmpeg', '-y', '-i', input_file]
            if quality == 'original':
                cmd.extend(['-c', 'copy'])
            else:
                cmd.extend(['-c:v', 'libx264', '-preset', 'fast'] + quality_settings + ['-c:a', 'aac'])
            cmd.append(output_path)
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            final_file = output_path

        elif conversion_type == 'mp4_to_m3u8':
            input_file = os.path.join(temp_dir, filenames[0])
            hls_dir = os.path.join(temp_dir, 'hls_output')
            os.makedirs(hls_dir, exist_ok=True)
            output_m3u8 = os.path.join(hls_dir, 'playlist.m3u8')
            
            cmd = ['ffmpeg', '-y', '-i', input_file]
            if quality == 'original':
                cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-c:a', 'aac'])
            else:
                cmd.extend(['-c:v', 'libx264', '-preset', 'fast'] + quality_settings + ['-c:a', 'aac'])
            
            cmd.extend([
                '-profile:v', 'main', '-level', '3.0',
                '-start_number', '0', '-hls_time', '10', '-hls_list_size', '0',
                '-f', 'hls', output_m3u8
            ])
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            JOBS[job_id]['status'] = 'zipping'
            zip_path = os.path.join(temp_dir, 'playlist_hls')
            shutil.make_archive(zip_path, 'zip', hls_dir)
            final_file = zip_path + '.zip'

        JOBS[job_id]['status'] = 'done'
        JOBS[job_id]['file_path'] = final_file

    except Exception as e:
        JOBS[job_id]['status'] = 'error'
        JOBS[job_id]['error'] = str(e)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/start', methods=['POST'])
def start_conversion():
    files = request.files.getlist('files')
    conversion_type = request.form.get('conversion_type')
    quality = request.form.get('quality')

    if not files or files[0].filename == '':
        return "Aucun fichier", 400

    job_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp()
    
    saved_filenames = []
    for f in files:
        fname = secure_filename(f.filename)
        f.save(os.path.join(temp_dir, fname))
        saved_filenames.append(fname)

    JOBS[job_id] = {'status': 'uploading'}

    thread = threading.Thread(target=process_video, args=(job_id, temp_dir, saved_filenames, conversion_type, quality))
    thread.start()

    return jsonify({'job_id': job_id})

@app.route('/status/<job_id>')
def check_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({'status': 'error', 'error': 'Job introuvable'})
    return jsonify(job)

@app.route('/download/<job_id>')
def download(job_id):
    job = JOBS.get(job_id)
    if not job or job['status'] != 'done':
        return "Fichier non prêt", 404
    
    file_path = job['file_path']
    filename = os.path.basename(file_path)
    return send_file(file_path, as_attachment=True, download_name=filename)

if __name__ == '__main__':
    # Render attribue dynamiquement le port, on récupère cette variable système
    port = int(os.environ.get('PORT', 10000))
    print(f"🚀 Serveur Docker/Render prêt sur le port {port} !")
    app.run(host='0.0.0.0', port=port)
