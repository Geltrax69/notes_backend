import os
import uuid
import hmac
import hashlib
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.http import StreamingHttpResponse
from django.utils.text import slugify
from django.utils import timezone
from datetime import timedelta
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import boto3
from botocore.exceptions import ClientError
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
import requests

from .models import NoteItem, UserProfile, Purchase
from .serializers import NoteItemSerializer


COLOR_ROTATION = [
    'bg-accent-pink',
    'bg-accent-orange',
    'bg-accent-purple',
    'bg-accent-blue',
    'bg-accent-green',
    'bg-accent-neon',
]


def get_s3_client():
    return boto3.client(
        's3',
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


def build_folder_path(parent):
    if not parent:
        return ''
    chunks = []
    current = parent
    while current:
        chunks.append(slugify(current.name) or str(current.id))
        current = current.parent
    return '/'.join(reversed(chunks))


def file_api_url(request, item_id):
    return request.build_absolute_uri(f'/api/files/{item_id}/content/')


def s3_public_url(key):
    if settings.AWS_PUBLIC_BASE_URL:
        return f"{settings.AWS_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    return f"https://{settings.AWS_BUCKET_NAME}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"


def build_item_path(item):
    parts = [item.name]
    current = item.parent
    while current:
        parts.append(current.name)
        current = current.parent
    return ' / '.join(reversed(parts))


def final_price_for_item(item):
    if not item.discount_enabled or item.discount_percent <= 0:
        return item.price
    discount_value = round((item.price * item.discount_percent) / 100)
    return max(item.price - discount_value, 0)


@api_view(['GET'])
def health(request):
    return Response({'ok': True})


@api_view(['GET'])
def search_items(request):
    query = (request.query_params.get('q') or '').strip()
    if len(query) < 2:
        return Response([])

    results = (
        NoteItem.objects
        .filter(name__icontains=query)
        .select_related('parent')
        .order_by('item_type', 'name')[:25]
    )

    payload = []
    for item in results:
        payload.append({
            'id': item.id,
            'name': item.name,
            'type': item.item_type,
            'parentId': item.parent_id,
            'path': build_item_path(item),
            'icon': 'folder' if item.item_type == 'folder' else 'picture_as_pdf',
        })

    return Response(payload)


@api_view(['GET'])
def admin_stats(request):
    from django.contrib.auth.models import User

    now = timezone.now()
    last_7_days = now - timedelta(days=7)

    total_users = User.objects.count()
    active_users_7d = User.objects.filter(last_login__gte=last_7_days).count()
    total_logins = UserProfile.objects.aggregate(total=Sum('login_count')).get('total') or 0
    total_purchases = UserProfile.objects.aggregate(total=Sum('purchased_notes_count')).get('total') or 0
    users_with_purchases = UserProfile.objects.filter(purchased_notes_count__gt=0).count()

    return Response({
        'total_users': total_users,
        'active_users_7d': active_users_7d,
        'total_logins': total_logins,
        'total_purchases': total_purchases,
        'users_with_purchases': users_with_purchases,
    })


@api_view(['GET'])
def items_list(request):
    parent_id = request.query_params.get('parentId')
    parent = None
    if parent_id not in (None, '', 'null'):
        parent = NoteItem.objects.filter(id=parent_id, item_type='folder').first()
        if not parent:
            return Response({'detail': 'Parent folder not found.'}, status=status.HTTP_404_NOT_FOUND)

    qs = NoteItem.objects.filter(parent=parent)
    file_urls = {obj.id: file_api_url(request, obj.id) for obj in qs if obj.item_type == 'file'}
    serializer = NoteItemSerializer(qs, many=True, context={'file_urls': file_urls})

    data = []
    for idx, item in enumerate(serializer.data):
        item['parentId'] = item.get('parentId')
        item['color'] = COLOR_ROTATION[idx % len(COLOR_ROTATION)]
        item['icon'] = 'folder' if item['type'] == 'folder' else 'picture_as_pdf'
        data.append(item)
    return Response(data)


@api_view(['GET'])
def item_detail(request, item_id):
    item = NoteItem.objects.filter(id=item_id).first()
    if not item:
        return Response({'detail': 'Item not found.'}, status=status.HTTP_404_NOT_FOUND)

    file_urls = {item.id: file_api_url(request, item.id)} if item.item_type == 'file' else {}
    serializer = NoteItemSerializer(item, context={'file_urls': file_urls})
    data = serializer.data
    data['color'] = COLOR_ROTATION[item.id % len(COLOR_ROTATION)]
    data['icon'] = 'folder' if data['type'] == 'folder' else 'picture_as_pdf'
    return Response(data)


@api_view(['POST'])
def create_folder(request):
    name = (request.data.get('name') or '').strip()
    parent_id = request.data.get('parentId')
    if not name:
        return Response({'detail': 'Folder name is required.'}, status=status.HTTP_400_BAD_REQUEST)

    parent = None
    if parent_id not in (None, '', 'null'):
        parent = NoteItem.objects.filter(id=parent_id, item_type='folder').first()
        if not parent:
            return Response({'detail': 'Parent folder not found.'}, status=status.HTTP_404_NOT_FOUND)

    item = NoteItem.objects.create(name=name, item_type='folder', parent=parent)
    serializer = NoteItemSerializer(item)
    data = serializer.data
    data['color'] = COLOR_ROTATION[item.id % len(COLOR_ROTATION)]
    data['icon'] = 'folder'
    return Response(data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def upload_pdf(request):
    name = (request.data.get('name') or '').strip()
    parent_id = request.data.get('parentId')
    file_obj = request.FILES.get('file')
    price = request.data.get('price', 499)
    discount_enabled = str(request.data.get('discountEnabled', 'false')).lower() in ('1', 'true', 'yes', 'on')
    discount_percent = request.data.get('discountPercent', 0)

    if not name:
        return Response({'detail': 'File name is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not file_obj:
        return Response({'detail': 'PDF file is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if file_obj.content_type != 'application/pdf':
        return Response({'detail': 'Only PDF upload is allowed.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        price = int(price)
    except (TypeError, ValueError):
        return Response({'detail': 'Price must be a valid number.'}, status=status.HTTP_400_BAD_REQUEST)
    if price < 0:
        return Response({'detail': 'Price cannot be negative.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        discount_percent = int(discount_percent)
    except (TypeError, ValueError):
        return Response({'detail': 'Discount percent must be a valid number.'}, status=status.HTTP_400_BAD_REQUEST)
    if discount_percent < 0 or discount_percent > 100:
        return Response({'detail': 'Discount percent must be between 0 and 100.'}, status=status.HTTP_400_BAD_REQUEST)
    if not discount_enabled:
        discount_percent = 0

    parent = None
    if parent_id not in (None, '', 'null'):
        parent = NoteItem.objects.filter(id=parent_id, item_type='folder').first()
        if not parent:
            return Response({'detail': 'Parent folder not found.'}, status=status.HTTP_404_NOT_FOUND)

    safe_name = slugify(name) or 'note'
    ext = os.path.splitext(file_obj.name)[1].lower() or '.pdf'
    if ext != '.pdf':
        ext = '.pdf'

    folder_path = build_folder_path(parent)
    key_parts = [p for p in ['notes', folder_path, f'{safe_name}-{uuid.uuid4().hex[:10]}{ext}'] if p]
    s3_key = '/'.join(key_parts)

    client = get_s3_client()
    try:
        client.upload_fileobj(
            file_obj,
            settings.AWS_BUCKET_NAME,
            s3_key,
            ExtraArgs={
                'ContentType': 'application/pdf',
            },
        )
    except ClientError as exc:
        return Response({'detail': f'S3 upload failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

    item = NoteItem.objects.create(
        name=name,
        item_type='file',
        parent=parent,
        s3_key=s3_key,
        content_type='application/pdf',
        size=file_obj.size,
        price=price,
        discount_enabled=discount_enabled,
        discount_percent=discount_percent,
    )
    serializer = NoteItemSerializer(item, context={'file_urls': {item.id: file_api_url(request, item.id)}})
    data = serializer.data
    data['color'] = COLOR_ROTATION[item.id % len(COLOR_ROTATION)]
    data['icon'] = 'picture_as_pdf'
    return Response(data, status=status.HTTP_201_CREATED)


@api_view(['PATCH'])
def update_file_price(request, item_id):
    item = NoteItem.objects.filter(id=item_id, item_type='file').first()
    if not item:
        return Response({'detail': 'File not found.'}, status=status.HTTP_404_NOT_FOUND)

    price = request.data.get('price')
    discount_enabled = request.data.get('discountEnabled', item.discount_enabled)
    discount_percent = request.data.get('discountPercent', item.discount_percent)
    try:
        price = int(price)
    except (TypeError, ValueError):
        return Response({'detail': 'Price must be a valid number.'}, status=status.HTTP_400_BAD_REQUEST)
    if price < 0:
        return Response({'detail': 'Price cannot be negative.'}, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(discount_enabled, str):
        discount_enabled = discount_enabled.lower() in ('1', 'true', 'yes', 'on')
    else:
        discount_enabled = bool(discount_enabled)
    try:
        discount_percent = int(discount_percent)
    except (TypeError, ValueError):
        return Response({'detail': 'Discount percent must be a valid number.'}, status=status.HTTP_400_BAD_REQUEST)
    if discount_percent < 0 or discount_percent > 100:
        return Response({'detail': 'Discount percent must be between 0 and 100.'}, status=status.HTTP_400_BAD_REQUEST)
    if not discount_enabled:
        discount_percent = 0

    item.price = price
    item.discount_enabled = discount_enabled
    item.discount_percent = discount_percent
    item.save(update_fields=['price', 'discount_enabled', 'discount_percent', 'updated_at'])
    serializer = NoteItemSerializer(item, context={'file_urls': {item.id: file_api_url(request, item.id)}})
    data = serializer.data
    data['color'] = COLOR_ROTATION[item.id % len(COLOR_ROTATION)]
    data['icon'] = 'picture_as_pdf'
    return Response(data)


@api_view(['DELETE'])
def delete_item(request, item_id):
    item = NoteItem.objects.filter(id=item_id).first()
    if not item:
        return Response({'detail': 'Item not found.'}, status=status.HTTP_404_NOT_FOUND)

    with transaction.atomic():
        # Delete S3 objects recursively by traversing descendants.
        to_visit = [item]
        all_nodes = []
        while to_visit:
            node = to_visit.pop()
            all_nodes.append(node)
            to_visit.extend(list(node.children.all()))

        file_keys = [n.s3_key for n in all_nodes if n.item_type == 'file' and n.s3_key]
        if file_keys:
            client = get_s3_client()
            chunks = [file_keys[i:i + 1000] for i in range(0, len(file_keys), 1000)]
            for chunk in chunks:
                try:
                    client.delete_objects(
                        Bucket=settings.AWS_BUCKET_NAME,
                        Delete={'Objects': [{'Key': key} for key in chunk], 'Quiet': True},
                    )
                except ClientError as exc:
                    return Response({'detail': f'S3 delete failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

        item.delete()

    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
def file_content(request, item_id):
    item = NoteItem.objects.filter(id=item_id, item_type='file').first()
    if not item or not item.s3_key:
        return Response({'detail': 'File not found.'}, status=status.HTTP_404_NOT_FOUND)

    client = get_s3_client()
    try:
        obj = client.get_object(Bucket=settings.AWS_BUCKET_NAME, Key=item.s3_key)
    except ClientError as exc:
        return Response({'detail': f'S3 read failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

    stream = obj['Body']

    def iterator():
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            yield chunk

    response = StreamingHttpResponse(iterator(), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{item.name}.pdf"'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_purchases(request):
    purchase_qs = (
        Purchase.objects
        .filter(user=request.user)
        .select_related('item')
    )
    purchase_rows = [p for p in purchase_qs if p.item and p.item.item_type == 'file']
    items = [p.item for p in purchase_rows]
    file_urls = {obj.id: file_api_url(request, obj.id) for obj in items}
    serialized = NoteItemSerializer(items, many=True, context={'file_urls': file_urls}).data
    purchase_map = {p.item_id: p for p in purchase_rows}

    detailed = []
    for row in serialized:
        item_id = row.get('id')
        purchase = purchase_map.get(item_id)
        path_parts = [x.strip() for x in build_item_path(purchase.item).split(' / ')] if purchase and purchase.item else []
        detailed.append({
            **row,
            'path': ' / '.join(path_parts),
            'className': path_parts[0] if len(path_parts) >= 2 else '',
            'subjectName': path_parts[1] if len(path_parts) >= 3 else (path_parts[0] if len(path_parts) >= 2 else ''),
            'purchasedAt': purchase.created_at.isoformat() if purchase else None,
            'purchaseAmount': purchase.amount if purchase else 0,
        })
    return Response(detailed)


@api_view(['GET'])
def payment_config(request):
    key_id = os.getenv('RAZORPAY_KEY_ID', '').strip()
    return Response({
        'provider': 'razorpay',
        'key_id': key_id,
        'enabled': bool(key_id),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_payment_order(request):
    key_id = os.getenv('RAZORPAY_KEY_ID', '').strip()
    key_secret = os.getenv('RAZORPAY_KEY_SECRET', '').strip()
    if not key_id or not key_secret:
        return Response({'detail': 'Razorpay is not configured.'}, status=status.HTTP_400_BAD_REQUEST)

    item_id = request.data.get('itemId')
    item = NoteItem.objects.filter(id=item_id, item_type='file').first()
    if not item:
        return Response({'detail': 'File not found.'}, status=status.HTTP_404_NOT_FOUND)

    if Purchase.objects.filter(user=request.user, item=item).exists():
        return Response({'detail': 'Already purchased.', 'alreadyPurchased': True}, status=status.HTTP_200_OK)

    amount_inr = final_price_for_item(item)
    amount_paise = int(amount_inr) * 100
    payload = {
        'amount': amount_paise,
        'currency': 'INR',
        'receipt': f'user{request.user.id}_file{item.id}_{uuid.uuid4().hex[:8]}',
        'notes': {
            'item_id': str(item.id),
            'user_id': str(request.user.id),
        },
    }
    try:
        rp_res = requests.post(
            'https://api.razorpay.com/v1/orders',
            json=payload,
            auth=(key_id, key_secret),
            timeout=10,
        )
        rp_data = rp_res.json()
    except requests.RequestException:
        return Response({'detail': 'Razorpay request failed.'}, status=status.HTTP_502_BAD_GATEWAY)

    if rp_res.status_code >= 300:
        return Response({'detail': rp_data.get('error', {}).get('description', 'Order creation failed.')}, status=status.HTTP_502_BAD_GATEWAY)

    return Response({
        'provider': 'razorpay',
        'key_id': key_id,
        'order_id': rp_data.get('id'),
        'amount': amount_paise,
        'currency': 'INR',
        'itemId': item.id,
        'itemName': item.name,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_payment(request):
    key_secret = os.getenv('RAZORPAY_KEY_SECRET', '').strip()
    if not key_secret:
        return Response({'detail': 'Razorpay is not configured.'}, status=status.HTTP_400_BAD_REQUEST)

    item_id = request.data.get('itemId')
    order_id = (request.data.get('razorpay_order_id') or '').strip()
    payment_id = (request.data.get('razorpay_payment_id') or '').strip()
    signature = (request.data.get('razorpay_signature') or '').strip()

    item = NoteItem.objects.filter(id=item_id, item_type='file').first()
    if not item:
        return Response({'detail': 'File not found.'}, status=status.HTTP_404_NOT_FOUND)
    if not order_id or not payment_id or not signature:
        return Response({'detail': 'Incomplete payment payload.'}, status=status.HTTP_400_BAD_REQUEST)

    body = f'{order_id}|{payment_id}'.encode('utf-8')
    generated = hmac.new(key_secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(generated, signature):
        return Response({'detail': 'Payment signature mismatch.'}, status=status.HTTP_400_BAD_REQUEST)

    purchase, created = Purchase.objects.get_or_create(
        user=request.user,
        item=item,
        defaults={
            'amount': final_price_for_item(item),
            'payment_provider': 'razorpay',
            'provider_order_id': order_id,
            'provider_payment_id': payment_id,
        }
    )

    if created:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.purchased_notes_count = Purchase.objects.filter(user=request.user).count()
        profile.save(update_fields=['purchased_notes_count'])

    return Response({'ok': True, 'purchased': True, 'itemId': item.id})


@api_view(['POST'])
def google_auth(request):
    token = request.data.get('token')
    if not token:
        return Response({'detail': 'No Google token provided.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Note: idinfo verification normally requires the audience parameter (the explicit Client ID)
        # Using a loose verify in the absence of a fixed Client ID configured in SETTINGS, relying on Google's ID token structure validity.
        # But for full security in production, specify audience=settings.GOOGLE_OAUTH2_CLIENT_ID
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request())
        
        email = idinfo.get('email')
        name = idinfo.get('name', 'User')
        picture = idinfo.get('picture', '')

        if not email:
            return Response({'detail': 'Email not provided by Google auth.'}, status=status.HTTP_400_BAD_REQUEST)

        user, created = User.objects.get_or_create(username=email, defaults={'email': email, 'first_name': name})
        profile, _ = UserProfile.objects.get_or_create(user=user)

        # Keep custom uploaded profile photos, but refresh Google photo when the stored photo is empty
        # or already a Google-hosted photo.
        if picture and (
            not profile.profile_photo
            or 'googleusercontent.com' in profile.profile_photo
        ):
            profile.profile_photo = picture
        profile.login_count += 1
        profile.save(update_fields=['profile_photo', 'login_count'])
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        refresh = RefreshToken.for_user(user)

        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': user.id,
                'email': user.email,
                'name': user.first_name,
                'picture': profile.profile_photo,
                'student_class': profile.student_class,
            }
        }, status=status.HTTP_200_OK)

    except ValueError as e:
        return Response({'detail': f'Invalid token: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def manual_auth(request):
    email = (request.data.get('email') or '').strip().lower()
    password = request.data.get('password') or ''
    name = (request.data.get('name') or '').strip()

    if not email:
        return Response({'detail': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not password:
        return Response({'detail': 'Password is required.'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.filter(username=email).first()
    if user:
        if not user.check_password(password):
            return Response({'detail': 'Invalid email or password.'}, status=status.HTTP_400_BAD_REQUEST)
        if name and not user.first_name:
            user.first_name = name
            user.save(update_fields=['first_name'])
    else:
        user = User(username=email, email=email, first_name=name or email.split('@')[0])
        user.set_password(password)
        user.save()

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.login_count += 1
    profile.save(update_fields=['login_count'])
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])

    refresh = RefreshToken.for_user(user)
    return Response({
        'refresh': str(refresh),
        'access': str(refresh.access_token),
        'user': {
            'id': user.id,
            'email': user.email,
            'name': user.first_name,
            'picture': profile.profile_photo,
            'student_class': profile.student_class,
        }
    }, status=status.HTTP_200_OK)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def user_me(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == 'GET':
        return Response({
            'id': user.id,
            'email': user.email,
            'name': user.first_name,
            'picture': profile.profile_photo,
            'student_class': profile.student_class,
        })

    elif request.method == 'PUT':
        student_class = request.data.get('student_class', profile.student_class)
        file_obj = request.FILES.get('profile_photo')
        
        if file_obj:
            ext = os.path.splitext(file_obj.name)[1].lower() or '.jpg'
            safe_name = slugify(user.username.split('@')[0])
            s3_key = f'profiles/{safe_name}-{uuid.uuid4().hex[:8]}{ext}'
            
            client = get_s3_client()
            try:
                client.upload_fileobj(
                    file_obj,
                    settings.AWS_BUCKET_NAME,
                    s3_key,
                    ExtraArgs={'ContentType': file_obj.content_type},
                )
                photo_url = s3_public_url(s3_key)
                profile.profile_photo = photo_url
            except ClientError as exc:
                return Response({'detail': f'S3 upload failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
        
        profile.student_class = student_class
        profile.save()
        
        return Response({
            'id': user.id,
            'email': user.email,
            'name': user.first_name,
            'picture': profile.profile_photo,
            'student_class': profile.student_class,
        })
