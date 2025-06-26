const backendUrl = "http://localhost:8000"; // Ensure your backend is running on this URL

// Helper function to update status messages
function updateStatus(elementId, message, type = '') {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = message;
        element.className = 'status-message'; // Reset classes
        if (type === 'upload') {
            element.classList.add('upload-status');
        } else if (type === 'question') {
            element.classList.add('question-status');
        }
        element.classList.add('visible'); // Make sure it's visible
        element.classList.add('animate-fade-in'); // Add animation
    }
}

// Helper function to disable/enable buttons and show/hide spinner
function setButtonLoading(buttonId, isLoading, defaultText, iconSvg) {
    const button = document.getElementById(buttonId);
    if (button) {
        button.disabled = isLoading;
        if (isLoading) {
            button.innerHTML = '<span class="spinner"></span> ' + (buttonId === 'uploadButton' ? 'Uploading...' : 'Processing...');
        } else {
            button.innerHTML = `<span class="button-content">${iconSvg} ${defaultText}</span>`;
        }
    }
}

async function uploadReport() {
    const fileInput = document.getElementById("fileInput");
    const answerCard = document.getElementById("answerCard");
    const answerText = document.getElementById("answerText");
    const questionStatus = document.getElementById("questionStatus");

    // Hide answer card and clear previous status messages on new upload attempt
    answerCard.style.display = 'none';
    answerCard.classList.remove('visible', 'animate-fade-in'); // Ensure classes are removed
    answerText.textContent = '';
    questionStatus.textContent = '';
    questionStatus.classList.remove('visible', 'animate-fade-in', 'question-status'); // Ensure question status is reset

    setButtonLoading('uploadButton', true, 'Upload Report', '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-upload"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/></svg>');
    updateStatus('uploadStatus', 'Uploading and processing your report...', 'upload');

    if (!fileInput.files.length) {
        updateStatus('uploadStatus', '❌ Please select a PDF file first.', 'upload');
        setButtonLoading('uploadButton', false, 'Upload Report', '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-upload"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/></svg>');
        return;
    }

    const file = fileInput.files[0];
    if (file.type !== 'application/pdf') {
        updateStatus('uploadStatus', '❌ Please upload a PDF file only.', 'upload');
        setButtonLoading('uploadButton', false, 'Upload Report', '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-upload"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/></svg>');
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
        const response = await fetch(`${backendUrl}/upload`, {
            method: "POST",
            body: formData,
        });

        const result = await response.json();
        updateStatus('uploadStatus', result.detail || "✅ Report uploaded successfully! You can now ask questions.", 'upload');
    } catch (err) {
        updateStatus('uploadStatus', "❌ Upload failed. Please check the backend server.", 'upload');
        console.error("Upload error:", err);
    } finally {
        setButtonLoading('uploadButton', false, 'Upload Report', '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-upload"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/></svg>');
    }
}

async function askQuestion() {
    const questionInput = document.getElementById("questionInput");
    const answerCard = document.getElementById("answerCard");
    const answerText = document.getElementById("answerText");

    const question = questionInput.value.trim();

    // Clear previous answer and status
    answerText.textContent = '';
    answerCard.classList.remove('visible', 'animate-fade-in');
    answerCard.style.display = 'none';

    setButtonLoading('askButton', true, 'Get Answer', '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-sparkles"><path d="M9.9 2.5l-3.6 5.8 5.8-3.6 5.8 3.6-3.6-5.8 3.6-5.8-5.8 3.6-5.8-3.6z"/><path d="M22 17.5l-2.7-4.4L15 17.5l2.7 4.4 2.7-4.4z"/><path d="M12.5 16.5l-1.8 2.9 2.9-1.8 2.9 1.8-1.8-2.9 1.8-2.9-2.9 1.8-2.9-1.8z"/></svg>');
    updateStatus('questionStatus', 'Processing your question...', 'question');

    if (!question) {
        updateStatus('questionStatus', '❌ Please enter a question.', 'question');
        setButtonLoading('askButton', false, 'Get Answer', '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-sparkles"><path d="M9.9 2.5l-3.6 5.8 5.8-3.6 5.8 3.6-3.6-5.8 3.6-5.8-5.8 3.6-5.8-3.6z"/><path d="M22 17.5l-2.7-4.4L15 17.5l2.7 4.4 2.7-4.4z"/><path d="M12.5 16.5l-1.8 2.9 2.9-1.8 2.9 1.8-1.8-2.9 1.8-2.9-2.9 1.8-2.9-1.8z"/></svg>');
        return;
    }

    try {
        const response = await fetch(`${backendUrl}/ask`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question }),
        });

        const result = await response.json();
        answerText.textContent = result.answer || "No answer found for your question.";
        
        answerCard.style.display = 'block';
        answerCard.classList.add('visible');
        answerCard.classList.add('animate-fade-in');

        updateStatus('questionStatus', '✅ Answer generated successfully!', 'question');
    } catch (err) {
        updateStatus('questionStatus', "❌ Failed to get answer. Please check the backend server.", 'question');
        console.error("Ask question error:", err);
    } finally {
        setButtonLoading('askButton', false, 'Get Answer', '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-sparkles"><path d="M9.9 2.5l-3.6 5.8 5.8-3.6 5.8 3.6-3.6-5.8 3.6-5.8-5.8 3.6-5.8-3.6z"/><path d="M22 17.5l-2.7-4.4L15 17.5l2.7 4.4 2.7-4.4z"/><path d="M12.5 16.5l-1.8 2.9 2.9-1.8 2.9 1.8-1.8-2.9 1.8-2.9-2.9 1.8-2.9-1.8z"/></svg>');
    }
}

// Attach event listeners after DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('uploadButton').addEventListener('click', uploadReport);
    document.getElementById('askButton').addEventListener('click', askQuestion);
});