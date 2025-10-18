from django.contrib import admin
from .models import Quiz, Question, Option, QuizAttempt, UserProfile, QuizRating, Server, ServerQuiz
# Register your models here.
admin.site.register(Quiz)
admin.site.register(Question)
admin.site.register(Option)
admin.site.register(QuizAttempt)
admin.site.register(UserProfile)
admin.site.register(QuizRating)
admin.site.register(Server)
admin.site.register(ServerQuiz)
