from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, DatabaseError, transaction
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.test import TestCase
from learning.models import Course, Chapter, KnowledgePoint
from learning.forms import ChapterForm, PointForm
from learning import services


class CurriculumTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('curriculum-owner')
        self.other = get_user_model().objects.create_user('curriculum-other')
        self.course = Course.objects.create(owner=self.user, name='数据库')
        self.other_course = Course.objects.create(owner=self.other, name='其他课程')
        self.chapter = services.save_chapter(self.user, self.course.pk, {'name':'关系设计'})
        self.section = services.save_chapter(self.user, self.course.pk, {'name':'规范化', 'parent':self.chapter})
        self.point = services.save_point(self.user, self.course.pk, {'name':'第三范式'})

    def test_old_points_remain_unassigned_and_can_be_assigned(self):
        self.assertIsNone(self.point.chapter_id)
        services.save_point(self.user,self.course.pk,{'name':self.point.name,'chapter':self.section},self.point.pk)
        self.point.refresh_from_db()
        self.assertEqual(self.point.chapter,self.section)
        # Legacy callers renaming a point must not accidentally unassign it.
        services.save_point(self.user,self.course.pk,{'name':'3NF'},self.point.pk)
        self.point.refresh_from_db()
        self.assertEqual(self.point.chapter,self.section)

    def test_no_cross_course_parent_or_point(self):
        foreign = Chapter.objects.create(course=self.other_course,name='他人章节')
        with self.assertRaises(ValidationError):
            services.save_chapter(self.user,self.course.pk,{'name':'非法', 'parent':foreign})
        with self.assertRaises(ValidationError):
            services.save_point(self.user,self.course.pk,{'name':'非法', 'chapter':foreign})

    def test_reject_cycle_depth_and_move_with_children(self):
        for pk,parent in [(self.chapter.pk,self.chapter),(self.chapter.pk,self.section)]:
            with self.assertRaises(ValidationError):
                services.save_chapter(self.user,self.course.pk,{'name':'关系设计','parent':parent},pk)
        with self.assertRaises(ValidationError):
            services.save_chapter(self.user,self.course.pk,{'name':'第三层','parent':self.section})
        another = Chapter.objects.create(course=self.course,name='另一章')
        with self.assertRaises(ValidationError):
            services.save_chapter(self.user,self.course.pk,{'name':'关系设计','parent':another},self.chapter.pk)

    def test_delete_protects_children_and_points(self):
        with self.assertRaises(ValidationError):
            services.delete_chapter(self.user,self.course.pk,self.chapter.pk)
        services.save_point(self.user,self.course.pk,{'name':'第三范式','chapter':self.section},self.point.pk)
        with self.assertRaises(ValidationError):
            services.delete_chapter(self.user,self.course.pk,self.section.pk)
        with self.assertRaises(ProtectedError):
            self.section.delete()
        empty = services.save_chapter(self.user,self.course.pk,{'name':'空章'})
        services.delete_chapter(self.user,self.course.pk,empty.pk)
        self.assertFalse(Chapter.objects.filter(pk=empty.pk).exists())

    def test_ownership_and_archive(self):
        with self.assertRaises(Http404):
            services.save_chapter(self.other,self.course.pk,{'name':'越权'})
        services.archive_course(self.user,self.course.pk,True)
        for action in [lambda:services.save_chapter(self.user,self.course.pk,{'name':'已归档'}),
                       lambda:services.delete_chapter(self.user,self.course.pk,self.section.pk),
                       lambda:services.save_point(self.user,self.course.pk,{'name':'第三范式','chapter':self.section},self.point.pk)]:
            with self.assertRaises(ValidationError): action()

    def test_forms_and_rendered_tree(self):
        foreign = Chapter.objects.create(course=self.other_course,name='他人章节')
        self.assertNotIn(foreign,PointForm(course=self.course).fields['chapter'].queryset)
        self.assertNotIn(self.section,ChapterForm(course=self.course).fields['parent'].queryset)
        self.client.force_login(self.user)
        response=self.client.get(f'/courses/{self.course.pk}/')
        self.assertContains(response,'课程目录')
        self.assertContains(response,'待归类知识点')
        self.assertContains(response,'规范化')
        self.assertNotContains(response,'他人章节')
        self.assertEqual(self.client.get(f'/courses/{self.other_course.pk}/chapters/new/').status_code,404)

    def test_post_create_edit_assign_delete(self):
        self.client.force_login(self.user)
        base=f'/courses/{self.course.pk}'
        self.assertEqual(self.client.post(base+'/chapters/new/',{'name':'SQL','position':1,'parent':''}).status_code,302)
        created=Chapter.objects.get(course=self.course,name='SQL')
        self.assertEqual(self.client.post(base+f'/chapters/{created.pk}/edit/',{'name':'SQL查询','position':2,'parent':''}).status_code,302)
        self.assertEqual(self.client.post(base+f'/points/{self.point.pk}/edit/',{'name':'第三范式','chapter':self.section.pk}).status_code,302)
        self.point.refresh_from_db()
        self.assertEqual(self.point.chapter_id,self.section.pk)
        self.assertEqual(self.client.post(base+f'/chapters/{created.pk}/delete/').status_code,302)

    def test_database_guards_reject_bypassed_validation(self):
        if connection.vendor != 'mysql':
            self.skipTest('MySQL trigger acceptance')
        foreign = Chapter.objects.create(course=self.other_course,name='他人章节')
        changes=[lambda:Chapter.objects.filter(pk=self.chapter.pk).update(parent_id=self.chapter.pk),
                 lambda:Chapter.objects.filter(pk=self.chapter.pk).update(parent_id=self.section.pk),
                 lambda:Chapter.objects.filter(pk=self.section.pk).update(parent_id=foreign.pk),
                 lambda:Chapter.objects.filter(pk=self.section.pk).update(course_id=self.other_course.pk),
                 lambda:KnowledgePoint.objects.filter(pk=self.point.pk).update(chapter_id=foreign.pk),
                 lambda:Chapter.objects.create(course=self.course,name='第三层',parent=self.section)]
        for change in changes:
            with self.assertRaises(DatabaseError),transaction.atomic(): change()

    def test_database_cannot_transfer_course_and_its_history_to_another_account(self):
        if connection.vendor != 'mysql':
            self.skipTest('MySQL owner guard')
        with self.assertRaises(DatabaseError), transaction.atomic():
            Course.objects.filter(pk=self.course.pk).update(owner=self.other)
        self.course.refresh_from_db()
        self.assertEqual(self.course.owner,self.user)
        Course.objects.filter(pk=self.course.pk).update(name='数据库原理')
        self.course.refresh_from_db()
        self.assertEqual(self.course.name,'数据库原理')
