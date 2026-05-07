from django import template
from store.models import Category
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def menu():
    categories = Category.objects.all()

    html = render_to_string("store/menu.html", {"categories": categories})
    return mark_safe(html)