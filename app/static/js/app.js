document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const uploadSection = document.getElementById('upload-section');
    const processingSection = document.getElementById('processing-section');
    const resultsSection = document.getElementById('results-section');
    
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('video-file-input');
    const selectBtn = dropzone.querySelector('.btn-primary');
    
    const progressCircle = document.getElementById('progress-circle');
    const progressPercent = document.getElementById('progress-percent');
    const metricFrames = document.getElementById('metric-frames');
    const taskState = document.getElementById('task-state');
    
    const livePersons = document.getElementById('live-stat-persons');
    const liveHelmets = document.getElementById('live-stat-helmets');
    const liveViolations = document.getElementById('live-stat-violations');
    
    const processedVideo = document.getElementById('processed-video-player');
    const downloadVideoBtn = document.getElementById('btn-download-video');
    const restartBtn = document.getElementById('btn-restart');
    
    const resTotalPersons = document.getElementById('res-total-persons');
    const resTotalHelmets = document.getElementById('res-total-helmets');
    const resTotalViolations = document.getElementById('res-total-violations');
    const compliancePercent = document.getElementById('compliance-percentage');
    const complianceGauge = document.querySelector('.compliance-score');
    const complianceVerdict = document.getElementById('compliance-verdict');
    
    let statusInterval = null;
    
    // --- SVG Circle Setup ---
    const radius = progressCircle.r.baseVal.value;
    const circumference = radius * 2 * Math.PI;
    progressCircle.style.strokeDasharray = `${circumference} ${circumference}`;
    progressCircle.style.strokeDashoffset = circumference;

    function setProgress(percent) {
        const offset = circumference - (percent / 100) * circumference;
        progressCircle.style.strokeDashoffset = offset;
        progressPercent.innerText = `${Math.round(percent)}%`;
    }

    // --- Switch Screens Helper ---
    function showSection(section) {
        uploadSection.classList.remove('active');
        processingSection.classList.remove('active');
        resultsSection.classList.remove('active');
        
        section.classList.add('active');
    }

    // --- Dropzone Logic ---
    dropzone.addEventListener('click', () => fileInput.click());
    
    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });
    
    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });
    
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleVideoUpload(e.dataTransfer.files[0]);
        }
    });
    
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleVideoUpload(e.target.files[0]);
        }
    });

    // --- Upload and Start Polling ---
    function handleVideoUpload(file) {
        const formData = new FormData();
        formData.append('file', file);
        
        // Show processing state immediately
        setProgress(0);
        taskState.innerText = 'Uploading...';
        taskState.className = 'badge-status yellow';
        metricFrames.innerText = '0 / --';
        livePersons.innerText = '0';
        liveHelmets.innerText = '0';
        liveViolations.innerText = '0';
        showSection(processingSection);
        
        fetch('/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => { throw new Error(err.detail || 'Upload failed') });
            }
            return response.json();
        })
        .then(data => {
            const taskId = data.task_id;
            startPolling(taskId);
        })
        .catch(err => {
            alert(`Error: ${err.message}`);
            showSection(uploadSection);
        });
    }

    // --- Polling loop ---
    function startPolling(taskId) {
        if (statusInterval) clearInterval(statusInterval);
        
        statusInterval = setInterval(() => {
            fetch(`/status/${taskId}`)
            .then(res => {
                if (!res.ok) throw new Error('Could not fetch status');
                return res.json();
            })
            .then(status => {
                // Update UI progress
                setProgress(status.progress);
                metricFrames.innerText = `${status.frames_processed} / ${status.total_frames || 'Calculating'}`;
                taskState.innerText = status.status.toUpperCase();
                
                // Update Live stats
                livePersons.innerText = status.stats.persons || 0;
                liveHelmets.innerText = status.stats.helmets || 0;
                liveViolations.innerText = status.stats.violations || 0;
                
                if (status.status === 'completed') {
                    clearInterval(statusInterval);
                    finishProcessing(taskId, status);
                } else if (status.status === 'failed') {
                    clearInterval(statusInterval);
                    alert(`Processing failed: ${status.error || 'Unknown error'}`);
                    showSection(uploadSection);
                }
            })
            .catch(err => {
                console.error(err);
            });
        }, 1000);
    }

    // --- Finish & Render Report ---
    function finishProcessing(taskId, finalStatus) {
        const stats = finalStatus.stats;
        
        // Final Results stats mapping
        resTotalPersons.innerText = stats.persons;
        resTotalHelmets.innerText = stats.helmets;
        resTotalViolations.innerText = stats.violations;
        
        // Calculate compliance percentage
        const totalChecked = stats.persons; // We evaluate all riders detected
        let compliance = 100;
        
        if (totalChecked > 0) {
            // Persons without violations / total checked
            const compliant = Math.max(0, totalChecked - stats.violations);
            compliance = (compliant / totalChecked) * 100;
        }
        
        compliancePercent.innerText = `${Math.round(compliance)}%`;
        
        // Style compliance gauge and verdict card
        if (compliance < 75) {
            complianceGauge.classList.add('low-safety');
            complianceVerdict.className = 'alert-box danger';
            complianceVerdict.innerHTML = `
                <i class="fa-solid fa-triangle-exclamation animate-pulse"></i>
                <div class="alert-text">
                    <h4>Low Safety Standards Detect</h4>
                    <p>High number of helmet violations detected. Safety measures need immediate improvement.</p>
                </div>
            `;
        } else {
            complianceGauge.classList.remove('low-safety');
            complianceVerdict.className = 'alert-box';
            complianceVerdict.innerHTML = `
                <i class="fa-solid fa-circle-check"></i>
                <div class="alert-text">
                    <h4>High Safety Standards Met</h4>
                    <p>Good helmet adoption rate. Standard road traffic safety compliance observed.</p>
                </div>
            `;
        }
        
        // Configure videos
        processedVideo.src = `/video/${taskId}`;
        downloadVideoBtn.href = `/video/${taskId}`;
        
        // Transition to results screen
        setTimeout(() => {
            showSection(resultsSection);
            processedVideo.load();
        }, 500);
    }

    // --- Restart handler ---
    restartBtn.addEventListener('click', () => {
        fileInput.value = '';
        processedVideo.src = '';
        showSection(uploadSection);
    });
});
