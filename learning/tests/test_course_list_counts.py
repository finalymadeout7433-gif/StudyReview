from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from learning.models import Course, Chapter, KnowledgePoint, Task, WrongQuestion


class CourseListCountsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('course-count-owner')
        self.other = get_user_model().objects.create_user('course-count-other')
        self.client.force_login(self.user)

    def test_independent_counts_empty_course_archive_and_owner_scope(self):
        full = Course.objects.create(owner=self.user, name='A full')
        empty = Course.objects.create(owner=self.user, name='B empty')
        archived = Course.objects.create(owner=self.user, name='C archived', is_archived=True)
        Course.objects.create(owner=self.other, name='Private')
        root = Chapter.objects.create(course=full, name='Root')
        Chapter.objects.create(course=full, parent=root, name='Section')
        for n in range(3):
            KnowledgePoint.objects.create(course=full, chapter=root, name=f'Point {n}')
        for n in range(4):
            Task.objects.create(course=full, title=f'Task {n}', due_date=timezone.localdate())
        for n in range(6):
            WrongQuestion.objects.create(course=full, title=f'Question {n}', content='Synthetic',
                original_answer='Synthetic', correct_answer='Synthetic', error_reason='Synthetic',
                next_review_date=timezone.localdate()+timedelta(days=1), is_archived=n==5)
        response = self.client.get('/courses/')
        self.assertEqual(response.status_code, 200)
        courses = list(response.context['page_obj'])
        self.assertEqual([c.pk for c in courses], [full.pk, empty.pk])
        self.assertEqual([(c.chapter_count, c.point_count, c.task_count, c.question_count) for c in courses],
                         [(2, 3, 4, 5), (0, 0, 0, 0)])
        self.assertEqual([c.pk for c in self.client.get('/courses/?archive=archived').context['page_obj']], [archived.pk])
        self.assertEqual(self.client.get('/courses/?archive=all').context['page_obj'].paginator.count, 3)

    def test_pagination_has_twenty_rows_and_stable_total_without_foreign_courses(self):
        Course.objects.bulk_create([Course(owner=self.user, name=f'Course {n:02d}') for n in range(24)])
        Course.objects.create(owner=self.other, name='Foreign')
        first = self.client.get('/courses/').context['page_obj']
        second = self.client.get('/courses/?page=2').context['page_obj']
        self.assertEqual((len(first), len(second), first.paginator.count, second.paginator.num_pages), (20, 4, 24, 2))
        self.assertFalse({c.pk for c in first} & {c.pk for c in second})
        self.assertTrue(all(c.question_count == 0 for c in second))
