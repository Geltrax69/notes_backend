from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    student_class = models.CharField(max_length=50, blank=True, default='')
    profile_photo = models.CharField(max_length=1024, blank=True, default='')
    login_count = models.PositiveIntegerField(default=0)
    purchased_notes_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.user.username}'s Profile"


class NoteItem(models.Model):
    ITEM_TYPES = (
        ('folder', 'Folder'),
        ('file', 'File'),
    )

    name = models.CharField(max_length=255)
    item_type = models.CharField(max_length=10, choices=ITEM_TYPES)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='children',
    )
    s3_key = models.CharField(max_length=1024, blank=True, default='')
    content_type = models.CharField(max_length=120, blank=True, default='')
    size = models.BigIntegerField(null=True, blank=True)
    price = models.PositiveIntegerField(default=499, validators=[MinValueValidator(0)])
    discount_enabled = models.BooleanField(default=False)
    discount_percent = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['item_type', 'name', 'id']

    def __str__(self):
        return f'{self.item_type}:{self.name}'


class Purchase(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='purchases')
    item = models.ForeignKey(NoteItem, on_delete=models.CASCADE, related_name='purchases')
    amount = models.PositiveIntegerField(default=0)
    payment_provider = models.CharField(max_length=32, default='razorpay')
    provider_order_id = models.CharField(max_length=128, blank=True, default='')
    provider_payment_id = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'item')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} -> {self.item_id}'
