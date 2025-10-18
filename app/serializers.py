from rest_framework import serializers
from django.contrib.auth.models import User
from app.models import (
    UserProfile, Quiz, QuizAttempt, Question, Option,
    QuizRating, Server, ServerQuiz
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from django.shortcuts import get_object_or_404

# ---------------------------
# User & Profile Serializers
# ---------------------------
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']


class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = ['id', 'user', 'bio', 'avatar', 'light_mode']


# ---------------------------
# Quiz & Related Serializers
# ---------------------------
class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ['id', 'text']


class QuestionSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = [
            'id', 'text', 'question_type', 'difficulty',
            'answer', 'user_answer', 'options'
        ]


class QuizRatingSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = QuizRating
        fields = ['id', 'user', 'rating']


class QuizSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)
    average_rating = serializers.FloatField(read_only=True)
    rating_distribution = serializers.SerializerMethodField()
    ratings = QuizRatingSerializer(many=True, read_only=True)
    user = UserSerializer(read_only=True)
    shared_with = UserSerializer(many=True, read_only=True)

    class Meta:
        model = Quiz
        fields = [
            'id', 'topic', 'difficulty', 'question_preference',
            'category', 'is_public', 'user', 'shared_with',
            'questions', 'average_rating', 'rating_distribution', 'ratings'
        ]

    def get_rating_distribution(self, obj):
        return obj.rating_distribution()


# ---------------------------
# Attempts
# ---------------------------
class QuizAttemptSerializer(serializers.ModelSerializer):
    quiz = QuizSerializer(read_only=True)

    class Meta:
        model = QuizAttempt
        fields = ['id', 'quiz', 'score', 'answers', 'created_at']


# ---------------------------
# Servers
# ---------------------------
class ServerSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    members = UserSerializer(many=True, read_only=True)

    class Meta:
        model = Server
        fields = ['id', 'name', 'description', 'code', 'created_by', 'members', 'created_at']


class ServerQuizSerializer(serializers.ModelSerializer):
    quiz = QuizSerializer(read_only=True)
    server = ServerSerializer(read_only=True)

    class Meta:
        model = ServerQuiz
        fields = ['id', 'server', 'quiz', 'assigned_at']