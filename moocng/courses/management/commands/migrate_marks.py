# -*- coding: utf-8 -*-
# Copyright 2013 Pablo Martín
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from datetime import datetime

from optparse import make_option

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import send_mail
from django.db.models import Max

from moocng.api.tasks import update_kq_mark, update_unit_mark, update_course_mark
from moocng.mongodb import get_db


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('-u', '--user',
                    action='store',
                    dest='user',
                    default="",
                    help='User pk'),
        make_option('-e', '--email-list',
                    action='store',
                    dest='email_list',
                    default="",
                    help='Email recipient list'),
    )

    def message(self, message):
        self.stdout.write("%s\n" % message.encode("ascii", "replace"))

    def update_passed(self, db, collection, passed_now, data):
        if not passed_now:
            return
        stats_collection = db.get_collection(collection)
        stats_collection.update(
            data,
            {'$inc': {'passed': 1}},
            safe=True
        )

    def handle(self, *args, **options):
        users = User.objects.all()
        if options["user"]:
            users = users.filter(pk=options["user"])
            if not users:
                raise CommandError(u"User %s does not exist" % options["user"])
            self.message("Migrating the user: %s" % users[0].username)
        elif settings.NUM_MIGRATE_MARK_DAILY is not None:
            email_list = options["email_list"]
            if not email_list:
                raise CommandError(u"Please you have to pass the email list")
            first_day = datetime.strptime(settings.FIRST_DAY_MIGRATE_MARK, '%Y-%m-%d')
            today = datetime.today()
            num_days = (today - first_day).days
            start_pk = num_days * settings.NUM_MIGRATE_MARK_DAILY + 1
            end_pk = (num_days + 1) * settings.NUM_MIGRATE_MARK_DAILY
            self.message("Migrating the users from pk=%s to pk=%s " % (start_pk, end_pk))
            users = users.filter(pk__gte=start_pk, pk__lte=end_pk)
            max_pk = User.objects.aggregate(Max('pk'))['pk__max']
            if not users and end_pk >= max_pk:
                send_mail('The mark migration is finished',
                          'The mark migration is finished',
                          settings.DEFAULT_FROM_EMAIL,
                          email_list.split(','))
        db = get_db()
        for user in users:
            for course in user.courses_as_student.all():
                for unit in course.unit_set.scorables():
                    for kq in unit.knowledgequantum_set.all():
                        updated_kq, passed_kq_now = update_kq_mark(db, kq, user, course.threshold)
                        self.update_passed(db, 'stats_kq', passed_kq_now, {'kq_id': kq.pk})
                    updated_unit, passed_unit_now = update_unit_mark(db, unit, user, course.threshold)
                    self.update_passed(db, 'stats_unit', passed_unit_now, {'unit_id': unit.pk})
                updated_course, passed_course_now = update_course_mark(db, course, user)
                self.update_passed(db, 'stats_course', passed_course_now, {'course_id': course.pk})
