# quizhippo/views.py
from django.contrib.auth import authenticate
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from rest_framework.permissions import IsAuthenticated
from rest_framework import status, permissions, parsers
from django.db.models import Avg
from django.db.models import Max
from django.db.models import Q
from app.models import (
    Quiz, Question, 
    Option, UserProfile, 
    QuizAttempt, ServerQuiz, 
    Server, QuizRating
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import api_view
from processing import (
    fetch_text_from_url,
    extract_text_from_pdf,
    parse_quiz_response,
)
from services import (
    generate__quiz, 
    assistant,
    check_multiple_choice,
    check_short_answer,
)
from constants import (
    LANGUAGES,
    DEFAULT_LANGUAGE,
    DIFFICULTY_LEVELS,
    DEFAULT_DIFFICULTY,
    QUESTION_TYPES,
    DEFAULT_QUESTION_TYPE,
    CHOOSE_OPTIONS,
    DEFAULT_CHOOSE,
    QUIZ_CATEGORIES,
)
from .serializers import (
    UserProfileSerializer, QuizSerializer, QuizAttemptSerializer,
    QuestionSerializer, OptionSerializer, QuizRatingSerializer,
    ServerSerializer, ServerQuizSerializer
)

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response(
                {"error": "Username and password are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(username=username, password=password)
        if user is not None:
            refresh = RefreshToken.for_user(user)
            return Response({
                "message": "Login successful",
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                },
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                }
            }, status=status.HTTP_200_OK)
        else:
            return Response(
                {"error": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email", "")

        if not username or not password:
            return Response(
                {"error": "Username and password are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(username=username).exists():
            return Response(
                {"error": "User already exists"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.create_user(username=username, password=password, email=email)
        refresh = RefreshToken.for_user(user)

        return Response({
            "message": "User registered successfully",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
            },
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        }, status=status.HTTP_201_CREATED)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"message": "Logout successful"}, status=status.HTTP_205_RESET_CONTENT)
        except Exception:
            return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)

class GenerateQuizAPI(APIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]

    def post(self, request, *args, **kwargs):
        try:
            # Extract input data safely
            topic = request.data.get('topic', 'General')
            language = request.data.get('language', 'English')
            num_questions = int(request.data.get('quiz_count', 5))
            difficulty = int(request.data.get('difficulty', 1))
            question_preference = request.data.get('quiz_type', 'MIX').upper()
            category = request.data.get('category', 'General')
            prompt = request.data.get('input_prompt', '').strip()
            url = request.data.get('input_url', '').strip()
            text = request.data.get('input_text', '').strip()
            upload_file = request.FILES.get('input_pdf')

            # Determine content source
            if prompt:
                content_source = prompt
            elif url:
                content_source = fetch_text_from_url(url)
            elif text:
                content_source = text
            elif upload_file and upload_file.name.endswith(".pdf"):
                content_source = extract_text_from_pdf(upload_file)
            else:
                content_source = topic

            # Generate quiz content (AI or custom logic)
            raw_quiz = generate__quiz(
                topic=topic,
                language=language,
                num_questions=num_questions,
                difficulty=difficulty,
                question_type=question_preference,
                content=content_source,
            )

            parsed_quiz = parse_quiz_response(raw_quiz)

            # Create Quiz instance
            quiz = Quiz.objects.create(
                topic=parsed_quiz.get("topic", topic),
                difficulty=int(parsed_quiz.get("difficulty", difficulty)),
                category=parsed_quiz.get("category", category),
                question_preference=question_preference,
                user=request.user if request.user.is_authenticated else None,
            )

            # Create Questions + Options
            for q in parsed_quiz.get("questions", []):
                question = Question.objects.create(
                    quiz=quiz,
                    text=q["text"],
                    question_type=q["type"].upper(),
                    difficulty=int(q.get("difficulty", difficulty)),
                    answer=q["answer"]
                )

                if q["type"].upper() == "MCQ" and q.get("mcq_options"):
                    for opt in q["mcq_options"]:
                        Option.objects.create(question=question, text=opt.strip())

            # ✅ Use correct related_name ("questions" and "options")
            quiz_data = {
                "id": quiz.id,
                "topic": quiz.topic,
                "difficulty": quiz.difficulty,
                "category": quiz.category,
                "question_preference": quiz.question_preference,
                "questions": [
                    {
                        "id": q.id,
                        "text": q.text,
                        "type": q.question_type,
                        "difficulty": q.difficulty,
                        "answer": q.answer,
                        "options": [o.text for o in q.options.all()],
                    }
                    for q in quiz.questions.all()
                ],
            }

            # Build response
            response_data = {
                "status": "success",
                "message": "Quiz generated successfully.",
                "quiz": quiz_data,
                "meta": {
                    "languages": LANGUAGES,
                    "default_language": DEFAULT_LANGUAGE,
                    "levels": DIFFICULTY_LEVELS,
                    "default_level": DEFAULT_DIFFICULTY,
                    "question_types": QUESTION_TYPES,
                    "default_type": DEFAULT_QUESTION_TYPE,
                    "choose_options": CHOOSE_OPTIONS,
                    "default_choose": DEFAULT_CHOOSE,
                },
            }

            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

@api_view(['POST'])
def chat_assistant(request):
    """
    Simple API endpoint to handle chat queries using your assistant function.
    """
    query = request.data.get('query', '').strip()

    if not query:
        return Response(
            {"error": "Query is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        response = assistant(query)
        return Response({"response": response}, status=status.HTTP_200_OK)
    except Exception as e:
        # Optional: log the error before returning response
        print(f"Error in chat_assistant: {e}")
        return Response(
            {"error": "Something went wrong while processing your request."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

class UpdatePreferencesAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """
        Update user preferences (e.g. light mode).
        """
        light_mode = request.data.get("light_mode")

        if light_mode is None:
            return Response(
                {"error": "Missing field 'light_mode'"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert "true"/"false" or "on"/"off" to boolean
        light_mode_bool = str(light_mode).lower() in ["true", "on", "1"]

        profile, created = UserProfile.objects.get_or_create(user=request.user)
        profile.light_mode = light_mode_bool
        profile.save()

        return Response(
            {
                "message": "Preferences updated successfully",
                "light_mode": profile.light_mode
            },
            status=status.HTTP_200_OK
        )
    
    def get(self, request):
        """
        Retrieve current user preferences.
        """
        try:
            profile = UserProfile.objects.get(user=request.user)
            return Response(
                {"light_mode": profile.light_mode},
                status=status.HTTP_200_OK
            )
        except UserProfile.DoesNotExist:
            # If no profile exists yet, assume default False
            return Response(
                {"light_mode": False},
                status=status.HTTP_200_OK
            )

class QuizPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 50

class AllQuizzesAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        quizzes = (Quiz.objects.filter(user=user) | Quiz.objects.filter(shared_with=user)).distinct()

        # Paginate
        paginator = QuizPagination()
        page = paginator.paginate_queryset(quizzes, request)
        serializer = QuizSerializer(page, many=True, context={'request': request})

        return paginator.get_paginated_response(serializer.data)
    
class CheckQuizAttempt(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        # Get all quizzes
        all_quizzes = Quiz.objects.all()

        # Get IDs of quizzes attempted by the user
        attempted_ids = QuizAttempt.objects.filter(user=user).values_list("quiz_id", flat=True)

        # Separate attempted and not attempted
        attempted = Quiz.objects.filter(id__in=attempted_ids)
        not_attempted = Quiz.objects.exclude(id__in=attempted_ids)

        # Build clean JSON response
        data = {
            "attempted": [
                {
                    "id": quiz.id,
                    "title": quiz.topic,
                    
                }
                for quiz in attempted
            ],
            "not_attempted": [
                {
                    "id": quiz.id,
                    "title": quiz.topic,
                    
                }
                for quiz in not_attempted
            ],
        }

        return Response(data, status=status.HTTP_200_OK)
    
class DeleteAccount(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user

        # Invalidate tokens before deleting
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass  # If token invalid, just ignore

        username = user.username
        user.delete()
        return Response(
            {"message": f"User '{username}' deleted successfully."},
            status=status.HTTP_200_OK
        )
    
class ChangePassword(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        old_password = request.data.get("password")
        new_password = request.data.get("new_password")

        if not old_password or not new_password:
            return Response(
                {"error": "Both old and new passwords are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user.check_password(old_password):
            return Response(
                {"error": "Incorrect current password."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save()

        return Response(
            {"message": "Password changed successfully."},
            status=status.HTTP_200_OK
        )
    
class DeleteQuiz(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, quiz_id):
        user = request.user
        quiz = get_object_or_404(Quiz, id=quiz_id, user=user)
        quiz.delete()
        return Response(
            {"message": "Quiz deleted successfully."},
            status=status.HTTP_200_OK
        )

class QuizVisibilityAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, quiz_id):
        """
        Toggle quiz visibility (public/private)
        """
        quiz = get_object_or_404(Quiz, id=quiz_id, user=request.user)
        is_public = request.data.get("is_public")

        # Validate input
        if is_public is None:
            return Response(
                {"error": "Missing field 'is_public'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert to boolean safely
        quiz.is_public = str(is_public).lower() in ["true", "1", "yes", "on"]
        quiz.save()

        return Response(
            {
                "message": f"Quiz visibility updated successfully!",
                "quiz_id": quiz.id,
                "is_public": quiz.is_public
            },
            status=status.HTTP_200_OK
        )

class ExploreQuizzesAPI(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, filter_type=None):
        quizzes = Quiz.objects.filter(is_public=True).annotate(
            avg_rating=Avg('ratings__rating')
        )

        category = request.GET.get("category")
        difficulty = request.GET.get("difficulty")

        # Apply category filter
        if category:
            quizzes = quizzes.filter(category__iexact=category)

        # Apply difficulty filter
        if difficulty:
            quizzes = quizzes.filter(difficulty=difficulty)

        # Apply "trending" filter
        if filter_type == "trending":
            quizzes = quizzes.filter(avg_rating__gt=3.5)
            active_filter = "trending"
        else:
            active_filter = "explore"

        # Prepare response data
        data = [
            {
                "id": quiz.id,
                "title": quiz.topic,
                "category": quiz.category,
                "difficulty": quiz.difficulty,
                "is_public": quiz.is_public,
                "avg_rating": quiz.avg_rating or 0,
                "created_by": quiz.user.username,
            }
            for quiz in quizzes
        ]

        return Response(
            {
                "active_filter": active_filter,
                "categories": QUIZ_CATEGORIES,
                "difficulty_levels": DIFFICULTY_LEVELS,
                "selected_category": category,
                "selected_difficulty": difficulty,
                "results": data,
            },
            status=status.HTTP_200_OK
        )

class ChangeUsernameOrEmailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request):
        """
        Update user's username, email, and profile image.
        """
        user = request.user
        new_username = request.data.get("new_username", "").strip()
        new_email = request.data.get("new_email", "").strip()
        profile_image = request.FILES.get("profile_image")

        # ✅ Validate and update username
        if new_username:
            if User.objects.filter(username=new_username).exclude(id=user.id).exists():
                return Response(
                    {"error": "Username already taken"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            user.username = new_username

        # ✅ Validate and update email
        if new_email:
            if User.objects.filter(email=new_email).exclude(id=user.id).exists():
                return Response(
                    {"error": "Email already in use"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            user.email = new_email

        user.save()

        # ✅ Update or create profile image
        profile, created = UserProfile.objects.get_or_create(user=user)
        if profile_image:
            profile.avatar = profile_image
            profile.save()

        return Response(
            {
                "message": "Profile updated successfully",
                "username": user.username,
                "email": user.email,
                "avatar": request.build_absolute_uri(profile.avatar.url) if profile.avatar else None,
            },
            status=status.HTTP_200_OK
        )

    def get(self, request):
        user = request.user

        try:
            profile = UserProfile.objects.get(user=user)
        except UserProfile.DoesNotExist:
            return Response(
                {"error": "User profile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        data = {
            "username": user.username,
            "email": user.email,
            "bio": profile.bio,
            "light_mode": profile.light_mode,
            "avatar": (
                request.build_absolute_uri(profile.avatar.url)
                if profile.avatar else None
            ),
        }

        return Response(data, status=status.HTTP_200_OK)
    
class RateQuizAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id)
        rating_value = int(request.data.get("rating", 0))

        if not (1 <= rating_value <= 5):
            return Response(
                {"error": "Rating must be between 1 and 5."},
                status=status.HTTP_400_BAD_REQUEST
            )

        QuizRating.objects.update_or_create(
            quiz=quiz,
            user=request.user,
            defaults={"rating": rating_value},
        )

        return Response(
            {"message": "Rating submitted successfully."},
            status=status.HTTP_200_OK
        )

class AddToMyQuizAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id)
        user = request.user

        if user in quiz.shared_with.all():
            # Optional: toggle behavior
            quiz.shared_with.remove(user)
            message = "Quiz removed from your list."
        else:
            quiz.shared_with.add(user)
            message = "Quiz added to your list."

        return Response(
            {"message": message},
            status=status.HTTP_200_OK
        )

class ProfileAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        # Try to get or create user profile
        profile, created = UserProfile.objects.get_or_create(user=user)

        # Fetch related data
        servers = Server.objects.filter(created_by=user)
        quizzes_created = Quiz.objects.filter(user=user).count()
        quizzes_completed = QuizAttempt.objects.filter(user=user).count()
        best_score = QuizAttempt.objects.filter(user=user).aggregate(
            Max('score')
        )['score__max'] or 0

        # Quizzes in user's servers
        server_quizzes = ServerQuiz.objects.filter(server__in=servers).values_list('quiz', flat=True)
        attempts = QuizAttempt.objects.filter(quiz__in=server_quizzes).select_related('user', 'quiz')

        # Build response
        data = {
            "username": user.username,
            "email": user.email,
            "avatar": (
                request.build_absolute_uri(profile.avatar.url)
                if profile.avatar
                else None
            ),
            "quizzes_created": quizzes_created,
            "quizzes_completed": quizzes_completed,
            "best_score": best_score,
            "servers": [
                {
                    "id": server.id,
                    "name": server.name,
                    "description": getattr(server, "description", ""),  # 👈 Added description
                    "created_at": server.created_at,
                }
                for server in servers
            ],
            "attempts": [
                {
                    "quiz_title": attempt.quiz.topic,
                    "score": attempt.score,
                    "date_attempted": attempt.created_at,
                    "user": attempt.user.username,
                }
                for attempt in attempts
            ],
        }

        return Response(data, status=status.HTTP_200_OK)
    
class ShareQuizAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id, user=request.user)
        username = request.data.get("username")

        if not username:
            return Response(
                {"error": "Username is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user_to_share = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response(
                {"error": f"User '{username}' does not exist."},
                status=status.HTTP_404_NOT_FOUND
            )

        # ✅ Add the user to the shared_with field
        quiz.shared_with.add(user_to_share)

        return Response(
            {"message": f"Quiz shared successfully with {username}."},
            status=status.HTTP_200_OK
        )
    
class CreateServerAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        name = request.data.get("name")
        description = request.data.get("description")

        if not name:
            return Response({"error": "Server name is required."}, status=status.HTTP_400_BAD_REQUEST)

        server = Server.objects.create(
            name=name,
            description=description or "",
            created_by=request.user
        )
        server.members.add(request.user)

        return Response(
            {
                "message": f"Server '{name}' created successfully!",
                "server_id": server.id,
                "code": server.code
            },
            status=status.HTTP_201_CREATED
        )
    
class JoinServerAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        code = request.data.get("code", "").strip().upper()

        if not code:
            return Response({"error": "Server code is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            server = Server.objects.get(code=code)
        except Server.DoesNotExist:
            return Response({"error": "Invalid code!"}, status=status.HTTP_404_NOT_FOUND)

        server.members.add(request.user)
        return Response(
            {"message": f"Joined '{server.name}' successfully!", "server_id": server.id},
            status=status.HTTP_200_OK
        )

class ServerListAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        # ✅ Fetch all servers where user is a member
        servers = Server.objects.filter(members=user).distinct()

        all_data = []

        for server in servers:
            # ✅ Get all quiz objects linked to this server
            server_quizzes = ServerQuiz.objects.filter(server=server).select_related('quiz')
            quizzes = [sq.quiz for sq in server_quizzes]  # extract the Quiz objects

            # ✅ Get all quizzes the user has attempted (only Quiz IDs)
            attempted_quiz_ids = QuizAttempt.objects.filter(
                user=user,
                quiz__in=quizzes
            ).values_list("quiz_id", flat=True)

            # ✅ Build the server data
            server_data = {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "code": server.code,
                "created_by": server.created_by.username,
                "created_at": server.created_at,
                "quizzes": [
                    {
                        "id": quiz.id,
                        "title": quiz.topic,
                        "category": quiz.category,
                        "is_public": quiz.is_public,
                        "attempted": quiz.id in attempted_quiz_ids,
                    }
                    for quiz in quizzes
                ],
            }

            all_data.append(server_data)

        return Response({"servers": all_data}, status=status.HTTP_200_OK)

class ServerDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, server_id):
        server = get_object_or_404(Server, id=server_id)

        # Only allow members to view
        if request.user not in server.members.all():
            return Response(
                {"error": "You are not a member of this server."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ✅ Fetch quiz IDs from the through model
        quiz_ids = server.quizzes.values_list("quiz", flat=True)
        quizzes = Quiz.objects.filter(id__in=quiz_ids)

        # ✅ Get user's attempted quizzes
        attempted_quiz_ids = QuizAttempt.objects.filter(
            user=request.user,
            quiz__in=quizzes
        ).values_list("quiz_id", flat=True)

        # ✅ Build response
        data = {
            "id": server.id,
            "name": server.name,
            "description": server.description,
            "code": server.code,
            "created_by": server.created_by.username,
            "created_at": server.created_at,
            "quizzes": [
                {
                    "id": quiz.id,
                    "title": quiz.topic,
                    "category": quiz.category,
                    "is_public": quiz.is_public,
                    "attempted": quiz.id in attempted_quiz_ids,
                }
                for quiz in quizzes
            ],
        }

        return Response(data, status=status.HTTP_200_OK)

class AddQuizToServerAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, server_id):
        server = get_object_or_404(Server, id=server_id)

        # Only server owner can add quizzes
        if request.user != server.created_by:
            return Response({"error": "You are not allowed to add quizzes to this server."}, status=status.HTTP_403_FORBIDDEN)

        quiz_id = request.data.get("quiz_id")
        if not quiz_id:
            return Response({"error": "quiz_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        quiz = get_object_or_404(Quiz, id=quiz_id)
        ServerQuiz.objects.create(server=server, quiz=quiz)

        return Response({"message": f"Quiz '{quiz.topic}' added to server '{server.name}' successfully."},
                        status=status.HTTP_201_CREATED)

class DeleteServerAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, server_id):
        server = get_object_or_404(Server, id=server_id)

        # Only the creator can delete the server
        if request.user != server.created_by:
            return Response(
                {"error": "You are not allowed to delete this server."},
                status=status.HTTP_403_FORBIDDEN
            )

        server_name = server.name
        server.delete()

        return Response(
            {"message": f"Server '{server_name}' deleted successfully."},
            status=status.HTTP_200_OK
        )
    
# class QuizDetailAPIView(APIView):
#     permission_classes = [permissions.IsAuthenticated]

#     def get(self, request, quiz_id):
#         quiz = get_object_or_404(Quiz, id=quiz_id)

#         # Get all related questions with their options
#         questions = quiz.questions.prefetch_related("options").all()

#         data = {
#             "id": quiz.id,
#             "topic": quiz.topic,
#             "category": quiz.category,
#             "difficulty": quiz.difficulty,
#             "is_public": quiz.is_public,
#             "created_by": quiz.user.username if quiz.user else None,
#             "average_rating": quiz.average_rating(),
#             "rating_distribution": quiz.rating_distribution(),
#             "questions": [
#                 {
#                     "id": q.id,
#                     "text": q.text,
#                     "question_type": q.question_type,
#                     "difficulty": q.difficulty,
#                     "options": [opt.text for opt in q.options.all()],
#                     "correct_answer": q.answer,  # ⚠️ optional — remove if you don’t want users to see this
#                 }
#                 for q in questions
#             ]
#         }

#         return Response(data, status=status.HTTP_200_OK)

class QuizDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id)

        # Build quiz data
        data = {
            "id": quiz.id,
            "topic": quiz.topic,
            "category": quiz.category,
            "difficulty": quiz.difficulty,
            "is_public": quiz.is_public,
            "created_by": quiz.user.username if quiz.user else None,
            "average_rating": quiz.average_rating(),
            "rating_distribution": quiz.rating_distribution(),
            "questions": []
        }

        # Get related questions and their options
        for q in quiz.questions.all():
            options = [opt.text for opt in q.options.all()]  # get all options for each question

            data["questions"].append({
                "id": q.id,
                "text": q.text,
                "question_type": q.question_type,
                "difficulty": q.difficulty,
                "options": options,  # all available options (if any)
                "answer": q.answer,  # ✅ include correct answer here
            })

        return Response(data, status=status.HTTP_200_OK)

class ResultView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id)
        
        # Get the latest attempt by the user for this quiz
        attempt = QuizAttempt.objects.filter(user=request.user, quiz=quiz).order_by('-created_at').first()
        if not attempt:
            return Response({"error": "No attempt found for this quiz."}, status=status.HTTP_404_NOT_FOUND)
        
        total_questions = quiz.questions.count()
        correct_answers = attempt.score
        incorrect_answers = total_questions - correct_answers

        # Prepare incorrect question details
        incorrect_questions = []
        for question in quiz.questions.all():
            user_answer = attempt.answers.get(str(question.id)) if attempt.answers else None
            if user_answer != question.answer:
                incorrect_questions.append({
                    "id": question.id,
                    "text": question.text,
                    "user_answer": user_answer,
                    "correct_answer": question.answer,
                })

        data = {
            "quiz": {
                "id": quiz.id,
                "topic": quiz.topic,
                "category": quiz.category,
                "difficulty": quiz.difficulty,
            },
            "attempt": {
                "id": attempt.id,
                "score": attempt.score,
                "total_questions": total_questions,
                "correct_answers": correct_answers,
                "incorrect_count": incorrect_answers,
                "date_attempted": attempt.created_at,
            },
            "incorrect_questions": incorrect_questions,
        }
        return Response(data, status=status.HTTP_200_OK)

# class QuizSubmitView(APIView):
#     permission_classes = [IsAuthenticated]  # Auth for both GET and POST

#     def get(self, request, quiz_id):
#         quiz = get_object_or_404(Quiz, id=quiz_id)
#         serializer = QuizSerializer(quiz)
#         # Extract questions to avoid duplication in response
#         quiz_data = serializer.data.copy()
#         questions = quiz_data.pop('questions', [])
#         return Response({
#             "quiz": quiz_data,
#             "questions": questions
#         })

#     def post(self, request, quiz_id):
#         quiz = get_object_or_404(Quiz, id=quiz_id)
#         questions = quiz.questions.all()

#         user_answers = request.data.get("answers", {})
#         # Removed the strict check to allow empty submissions (score 0)
#         # if not user_answers:
#         #     return Response({"error": "No answers submitted."}, status=status.HTTP_400_BAD_REQUEST)

#         marks = 0
#         for question in questions:
#             user_answer = user_answers.get(str(question.id))
#             if not user_answer:
#                 continue

#             if question.question_type == "SHORT":
#                 if check_short_answer(user_answer, question.answer):
#                     marks += 1
#             elif question.question_type == "MCQ":
#                 if check_multiple_choice(user_answer, question.answer):
#                     marks += 1
#             elif user_answer.strip().lower() == question.answer.strip().lower():
#                 marks += 1

#         attempt = QuizAttempt.objects.create(
#             user=request.user,
#             quiz=quiz,
#             score=marks,
#             answers=user_answers
#         )

#         total_questions = questions.count()
#         result_summary = {
#             "attempt_id": attempt.id,
#             "quiz_id": quiz.id,
#             "score": marks,
#             "total_questions": total_questions,
#             "correct_answers": marks,
#             "incorrect_answers": total_questions - marks,
#         }

#         return Response(result_summary, status=status.HTTP_201_CREATED)
    

class QuizSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id)
        serializer = QuizSerializer(quiz)
        quiz_data = serializer.data.copy()
        questions = quiz_data.pop('questions', [])
        return Response({
            "quiz": quiz_data,
            "questions": questions
        })

    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id)
        questions = quiz.questions.all()
        user_answers = request.data.get("answers", {})

        # Detect mode from path: /retake-quiz/ means update existing, else create new
        is_retake = 'retake-quiz' in request.path

        if is_retake:
            # Update existing (or create if none)
            attempt, created = QuizAttempt.objects.get_or_create(
                user=request.user,
                quiz=quiz,
                defaults={'score': 0, 'answers': {}}
            )
        else:
            # Always create new for initial play
            attempt = QuizAttempt.objects.create(
                user=request.user,
                quiz=quiz,
                score=0,
                answers={}
            )
            created = True  # Newly created in this branch

        # Calculate marks (same logic for both)
        marks = 0
        for question in questions:
            user_answer = user_answers.get(str(question.id))
            if not user_answer:
                continue

            if question.question_type == "SHORT":
                if check_short_answer(user_answer, question.answer):
                    marks += 1
            elif question.question_type == "MCQ":
                if check_multiple_choice(user_answer, question.answer):
                    marks += 1
            elif user_answer.strip().lower() == question.answer.strip().lower():
                marks += 1

        # Update attempt
        attempt.score = marks
        attempt.answers = user_answers
        attempt.save()

        total_questions = questions.count()
        result_summary = {
            "attempt_id": attempt.id,
            "quiz_id": quiz.id,
            "score": marks,
            "total_questions": total_questions,
            "correct_answers": marks,
            "incorrect_answers": total_questions - marks,
            "is_retake": is_retake,  # Optional: Pass back for frontend logging
        }

        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK  # 201 for new, 200 for update
        return Response(result_summary, status=status_code)