from django.template import Template, Context
from django.test import SimpleTestCase
from learning.templatetags.learning_display import clean_learning_title


class LearningDisplayTests(SimpleTestCase):
    def test_only_initial_prefix_is_removed(self):
        self.assertEqual(clean_learning_title('[示例] SQL约束'),'SQL约束')
        self.assertEqual(clean_learning_title('示例演练：使用外键'),'使用外键')
        self.assertEqual(clean_learning_title('比较示例与结果'),'比较示例与结果')

    def test_historical_text_is_still_escaped(self):
        text='[示例] <script>alert(1)</script>'
        html=Template('{% load learning_display %}{{ text|clean_learning_title }}').render(Context({'text':text}))
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>',html)
        self.assertEqual(text,'[示例] <script>alert(1)</script>')
