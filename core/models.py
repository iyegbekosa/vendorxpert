from django.db import models

# Create your models here.
class Faq(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    created_at = models.DateField(auto_now=True)
    updated_at = models.DateField(auto_now_add=True)
    approved = models.BooleanField(default=False)
    

    class Meta:
        ordering = ('-updated_at',)
    
    def __str__(self):
        return self.title

