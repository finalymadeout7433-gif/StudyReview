from django import template

register=template.Library()


@register.filter
def clean_learning_title(value):
    """Display imported prefixes cleanly without rewriting immutable snapshots."""
    text=str(value or '')
    for prefix in ('[示例] ', '示例演练：'):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text
