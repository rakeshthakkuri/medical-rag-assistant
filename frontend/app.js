const backendUrl = "http://localhost:8000";

async function uploadReport() {
  const fileInput = document.getElementById("fileInput");
  const uploadStatus = document.getElementById("uploadStatus");
  uploadStatus.textContent = "Uploading...";

  if (!fileInput.files.length) {
    uploadStatus.textContent = "❌ Please select a PDF file first.";
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  try {
    const response = await fetch(`${backendUrl}/upload`, {
      method: "POST",
      body: formData,
    });

    const result = await response.json();
    uploadStatus.textContent = result.detail || "✅ Upload complete!";
  } catch (err) {
    uploadStatus.textContent = "❌ Upload failed.";
    console.error(err);
  }
}

async function askQuestion() {
  const questionInput = document.getElementById("questionInput");
  const questionStatus = document.getElementById("questionStatus");
  const answerCard = document.getElementById("answerCard");
  const answerText = document.getElementById("answerText");

  const question = questionInput.value.trim();
  if (!question) {
    questionStatus.textContent = "❌ Please enter a question.";
    return;
  }

  questionStatus.textContent = "Thinking...";
  answerCard.style.display = "none";

  try {
    const response = await fetch(`${backendUrl}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    const result = await response.json();
    answerText.textContent = result.answer || "No answer found.";
    answerCard.style.display = "block";
    questionStatus.textContent = "";
  } catch (err) {
    questionStatus.textContent = "❌ Failed to get answer.";
    console.error(err);
  }
}
