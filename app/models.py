# quizapp/models.py
from django.db import models
import uuid
from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    light_mode = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username

class QuizRating(models.Model):
    quiz = models.ForeignKey('Quiz', on_delete=models.CASCADE, related_name='ratings')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField()

    class Meta:
        unique_together = ('quiz', 'user')

    def __str__(self):
        return f"{self.user.username} rated {self.quiz.topic} as {self.rating}"

class Quiz(models.Model):
    QUESTION_PREFERENCES = [
        ('SHORT', 'Short Questions'),
        ('TF', 'True/False'),
        ('MCQ', 'Multiple Choice'),
        ('FILL', 'Fill in the Blank'),
        ('MIX', 'Mix'),
    ]

    topic = models.CharField(max_length=200)
    difficulty = models.IntegerField(default=1)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name="quizzes")
    question_preference = models.CharField(max_length=10, choices=QUESTION_PREFERENCES, default="MIX")
    shared_with = models.ManyToManyField(User, related_name="shared_quizzes", blank=True)
    is_public = models.BooleanField(default=False)
    category = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.topic} (Difficulty {self.difficulty})"

    def average_rating(self):
        ratings = self.ratings.all()
        if ratings.exists():
            return round(sum(r.rating for r in ratings) / ratings.count(), 1)
        return 0

    def rating_distribution(self):
        """Return dict like {5: count, 4: count, ..., 1: count}"""
        distribution = {i: 0 for i in range(1, 6)}
        for r in self.ratings.all():
            distribution[r.rating] += 1
        return distribution

class Question(models.Model):
    QUESTION_TYPES = [
        ('MCQ', 'Multiple Choice'),
        ('TF', 'True/False'),
        ('SHORT', 'Short Answer'),
        ('FILL', 'Fill in the Blank'),
    ]

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    question_type = models.CharField(max_length=10, choices=QUESTION_TYPES)
    difficulty = models.IntegerField(default=1)
    answer = models.CharField(max_length=200)
    user_answer = models.CharField(max_length=1020, null=True, blank=True)

    def __str__(self):
        return self.text


class Option(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=200)

    def __str__(self):
        return self.text

class QuizAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)
    answers = models.JSONField(default=dict)  # e.g. {question_id: "user_answer"}
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.quiz.topic} ({self.score})"

class Server(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    code = models.CharField(max_length=8, unique=True, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="servers")
    members = models.ManyToManyField(User, related_name="joined_servers", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = str(uuid.uuid4())[:8].upper()  # unique join code
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ServerQuiz(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name="quizzes")
    quiz = models.ForeignKey('Quiz', on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quiz.topic} → {self.server.name}"
