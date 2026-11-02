from datetime import timedelta
import json
import uuid
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Course, KnowledgePoint, Task, WrongQuestion, ReviewRecord
from .services import MIN_STAT_DATE, MAX_STAT_DATE
from attachments.models import ImageRole

DATE_WIDGET = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class LoginForm(AuthenticationForm):
    username = forms.CharField(label='用户名', max_length=150, widget=forms.TextInput(attrs={'autocomplete': 'username'}))
    password = forms.CharField(label='密码', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))


class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs['autocomplete'] = 'username'
        self.fields['password1'].widget.attrs['autocomplete'] = 'new-password'
        self.fields['password2'].widget.attrs['autocomplete'] = 'new-password'


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['name', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if Course.objects.filter(owner=self.user, name=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('已有同名课程（归档课程也保留名称），请换一个名称。')
        return name


class PointForm(forms.ModelForm):
    class Meta:
        model = KnowledgePoint
        fields = ['name']

    def __init__(self, *args, course, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if KnowledgePoint.objects.filter(course=self.course, name=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('本课程已有同名知识点。')
        return name


class CourseOwnedForm(forms.ModelForm):
    token = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        courses = Course.objects.filter(owner=user, is_archived=False)
        self.fields['course'].queryset = courses
        self.fields['course'].empty_label = '请选择课程'
        self.fields['course'].label = '所属课程'
        if self.instance.pk:
            self.fields['course'].disabled = True
            self.fields['course'].help_text = '首版不支持跨课程迁移。'
        elif not self.is_bound and not self.initial.get('course'):
            first = courses.first()
            if first:
                self.initial['course'] = first.pk


class TaskForm(CourseOwnedForm):
    class Meta:
        model = Task
        fields = ['course', 'title', 'due_date', 'description']
        widgets = {'due_date': DATE_WIDGET, 'description': forms.Textarea(attrs={'rows': 4})}


class QuestionForm(CourseOwnedForm):
    image_payload = forms.CharField(required=False, max_length=16000, widget=forms.HiddenInput)
    knowledge_points = forms.ModelMultipleChoiceField(label='关联知识点', required=False,
        queryset=KnowledgePoint.objects.none(), widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = WrongQuestion
        fields = ['course', 'title', 'content', 'original_answer', 'correct_answer', 'error_reason', 'knowledge_points', 'next_review_date']
        widgets = {field: forms.Textarea(attrs={'rows': rows, 'maxlength': 20000}) for field, rows in
            [('content', 5), ('original_answer', 3), ('correct_answer', 4), ('error_reason', 3)]} | {'next_review_date': DATE_WIDGET}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        course_id = self.instance.course_id if self.instance.pk else (
            self.data.get('course') if self.is_bound else self.initial.get('course'))
        try:
            course_id = int(course_id)
        except (ValueError, TypeError):
            course_id = None
        self.fields['knowledge_points'].queryset = KnowledgePoint.objects.filter(
            course_id=course_id, course__owner=user, course__is_archived=False)
        self.fields['knowledge_points'].help_text = '只能选择本课程知识点；可不选。'
        self.fields['next_review_date'].help_text = '新题默认明天，可选今天或未来日期。'
        if not self.is_bound and not self.instance.pk:
            self.initial.setdefault('next_review_date', timezone.localdate() + timedelta(days=1))
        if not self.is_bound and self.instance.pk:
            self.initial['image_payload'] = json.dumps([
                {'id': str(link.attachment_id), 'role': link.role}
                for link in self.instance.image_links.all()])

    def clean_image_payload(self):
        try:
            rows = json.loads(self.cleaned_data.get('image_payload') or '[]')
            if not isinstance(rows, list) or len(rows) > 24:
                raise ValueError()
            groups = {role: [] for role in ImageRole.values}
            for row in rows:
                if not isinstance(row, dict) or set(row) != {'id', 'role'} or row['role'] not in groups:
                    raise ValueError()
                value = str(uuid.UUID(row['id']))
                if value in groups[row['role']]:
                    raise ValueError()
                groups[row['role']].append(value)
            if any(len(ids) > 12 for ids in groups.values()):
                raise ValueError()
        except (TypeError, ValueError, KeyError, AttributeError):
            raise forms.ValidationError('图片选择无效；每组最多12张，每题最多24张。')
        self.cleaned_data['image_groups'] = groups
        return json.dumps(rows)

    def clean_next_review_date(self):
        date = self.cleaned_data['next_review_date']
        if date < timezone.localdate() and (not self.instance.pk or date != self.instance.next_review_date):
            raise forms.ValidationError('请选择今天或未来的日期。')
        return date


class AnswerForm(forms.Form):
    answer = forms.CharField(label='本次作答', max_length=20000,
        widget=forms.Textarea(attrs={'rows': 5, 'placeholder': '先独立回忆并作答。不会时可写“未作答”。'}))
    token = forms.CharField(widget=forms.HiddenInput)


class ReviewForm(AnswerForm):
    rating = forms.ChoiceField(label='本次回忆情况', choices=[('', '请选择'),
        ('again', '未独立答对 / 看过答案'), ('hard', '独立答对，仍费力'), ('good', '独立正确，较熟练')],
        widget=forms.RadioSelect)
    next_review_date = forms.DateField(label='下次复习日期', required=False, widget=DATE_WIDGET,
        help_text='留空使用FSRS的日级建议；独立答对才选后两项。可手动改为晚于今天的日期。')
    note = forms.CharField(label='复习备注', required=False, max_length=5000, widget=forms.Textarea(attrs={'rows': 3}))

    def clean_next_review_date(self):
        date = self.cleaned_data.get('next_review_date')
        if date and date <= timezone.localdate():
            raise forms.ValidationError('下次复习必须晚于今天。')
        return date


class StatisticsForm(forms.Form):
    course = forms.ModelChoiceField(label='课程范围', required=False, queryset=Course.objects.none(), empty_label='全部活跃课程')
    start = forms.DateField(label='复习开始日期', widget=DATE_WIDGET)
    end = forms.DateField(label='复习结束日期', widget=DATE_WIDGET)
    review_source = forms.ChoiceField(label='记录范围', required=False, choices=[
        ('all', '全部记录'), ('personal', '我的复习'), ('example', '练习记录')])

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = Course.objects.filter(owner=user, is_archived=False)
        for name in ('start', 'end'):
            self.fields[name].widget.attrs.update({'min': MIN_STAT_DATE.isoformat(), 'max': MAX_STAT_DATE.isoformat()})
            self.fields[name].help_text = '支持 1900-01-01 至 2100-12-31。'

    def clean_start(self):
        return self.clean_supported_date('start')

    def clean_end(self):
        return self.clean_supported_date('end')

    def clean_supported_date(self, name):
        value = self.cleaned_data[name]
        if not MIN_STAT_DATE <= value <= MAX_STAT_DATE:
            raise forms.ValidationError('统计日期支持 1900-01-01 至 2100-12-31。')
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('start') and cleaned.get('end'):
            if cleaned['start'] > cleaned['end']:
                self.add_error('end', '结束日期不能早于开始日期。')
            elif (cleaned['end'] - cleaned['start']).days > 3650:
                self.add_error('end', '请选择不超过 10 年的日期范围。')
        return cleaned
