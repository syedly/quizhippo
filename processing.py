import requests
from bs4 import BeautifulSoup
import PyPDF2
import io
import re

def fetch_text_from_url(url: str) -> str:
    """
    Fetches and cleans text content from a webpage URL.
    """
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # remove unwanted tags
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
            tag.extract()

        # get visible text
        text = soup.get_text(separator=" ", strip=True)

        # collapse multiple spaces
        clean_text = " ".join(text.split())

        # limit to avoid sending huge data to AI
        return clean_text[:5000]
    except Exception as e:
        return f"Could not extract content from {url}: {e}"


def extract_text_from_pdf(file) -> str:
    """
    Extract text from an uploaded PDF file.
    `file` should be Django's InMemoryUploadedFile or TemporaryUploadedFile
    """
    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return " ".join(text.split())[:5000]  # limit to 5000 chars
    except Exception as e:
        return f"Could not extract text from PDF: {e}"

def incorrect_answer(quiz, attempt):
    total_questions = quiz.questions.count()
    if not attempt:
        return total_questions
    return total_questions - attempt.score

def parse_quiz_response(response_text):
    response_text = (response_text or "").strip()

    topic_match = re.search(r"Topic:\s*(.+?)\s*\(Difficulty\s*(\d+)\)", response_text, re.IGNORECASE)
    topic = topic_match.group(1).strip() if topic_match else "Untitled Quiz"
    quiz_difficulty = int(topic_match.group(2)) if topic_match else 1

    questions_part = ""
    answers_part = ""
    difficulty_part = ""
    if "Questions:" in response_text and "Answers:" in response_text:
        try:
            questions_part = response_text.split("Questions:")[1].split("Answers:")[0].strip()
            answers_part = response_text.split("Answers:")[1]
            if "Question Difficulty Levels:" in answers_part:
                answers_part, difficulty_part = answers_part.split("Question Difficulty Levels:")
                answers_part = answers_part.strip()
                difficulty_part = difficulty_part.strip()
            else:
                answers_part = answers_part.strip()
        except Exception:
            questions_part = ""
            answers_part = ""

    question_blocks = re.split(r"\n\s*\d+\.\s*", questions_part)
    if question_blocks and question_blocks[0].strip() == "":
        question_blocks = question_blocks[1:]

    answers = re.findall(r"\d+\.\s*(.+)", answers_part) if answers_part else []

    if not answers and answers_part:
        answers = [line.strip() for line in answers_part.splitlines() if line.strip()]

    difficulties = {}
    if difficulty_part:
        for line in difficulty_part.splitlines():
            m = re.search(r"Q\s*(\d+)\s*[^0-9]*\s*:?(\d+)", line) or re.search(r"(\d+)\.\s*Q\d+\s*→\s*Difficulty:\s*(\d+)", line)
            if not m:
                m = re.search(r"Q(\d+)\s*→\s*Difficulty:\s*(\d+)", line)
            if m:
                try:
                    q_idx = int(m.group(1))
                    q_diff = int(m.group(2))
                    difficulties[q_idx] = q_diff
                except Exception:
                    pass

    parsed_questions = []
    for idx, q_text in enumerate(question_blocks, start=1):
        text = q_text.strip()
        if not text:
            continue

        mcq_option_pattern = r"(?:\([a-z]\)|[a-z]\))\s*([^\n\r]+)"
        mcq_options = re.findall(mcq_option_pattern, text, flags=re.IGNORECASE)

        if re.search(r"True or False|True/False|True or false", text, re.IGNORECASE):
            q_type = "TF"
        elif mcq_options:
            q_type = "MCQ"
        elif re.search(r"_{3,}|____|blank", text, re.IGNORECASE):
            q_type = "FILL"
        else:
            q_type = "SHORT"

        if q_type == "MCQ":
            parts = re.split(r"(?:\n|\r\n)", text)
            non_option_lines = [p for p in parts if not re.match(r"^\s*(?:\([a-z]\)|[a-z]\))", p, re.IGNORECASE)]
            question_text_clean = " ".join(non_option_lines).strip()
        else:
            question_text_clean = text

        answer_text = ""
        if idx-1 < len(answers):
            answer_text = answers[idx-1].strip()
        parsed_questions.append({
            "text": question_text_clean,
            "raw_text": text,            
            "type": q_type,
            "answer": answer_text,
            "difficulty": difficulties.get(idx, quiz_difficulty),
            "mcq_options": mcq_options
        })

    return {
        "topic": topic,
        "difficulty": quiz_difficulty,
        "category": re.search(r"Category:\s*(.+)", response_text, re.IGNORECASE).group(1).strip() if re.search(r"Category:\s*(.+)", response_text, re.IGNORECASE) else "General",
        "questions": parsed_questions
    }