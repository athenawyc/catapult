# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import print_function
from __future__ import division
from __future__ import absolute_import

import uuid
import datetime

from dashboard.common import testing_common
from dashboard.common import utils
from dashboard.models import alert_group
from dashboard.models import alert_group_workflow
from dashboard.models import anomaly
from dashboard.models import subscription
from google.appengine.ext import ndb


class AlertGroupWorkflowTest(testing_common.TestCase):

  def setUp(self):
    super(AlertGroupWorkflowTest, self).setUp()
    self.maxDiff = None
    self._issue_tracker = testing_common.FakeIssueTrackerService()
    self._sheriff_config = testing_common.FakeSheriffConfigClient()

  @staticmethod
  def _AddAnomaly(**kwargs):
    default = {
        'test': 'master/bot/test_suite/measurement/test_case',
        'start_revision': 0,
        'end_revision': 100,
        'is_improvement': False,
        'median_before_anomaly': 1.1,
        'median_after_anomaly': 1.3,
        'ownership': {
            'component': 'Foo>Bar',
            'emails': ['x@google.com', 'y@google.com'],
        },
    }
    default.update(kwargs)
    default['test'] = utils.TestKey(default['test'])
    return anomaly.Anomaly(**default).put()

  @staticmethod
  def _AddAlertGroup(anomaly_key, issue=None, anomalies=None, status=None):
    anomaly_entity = anomaly_key.get()
    group = alert_group.AlertGroup(
        id=str(uuid.uuid4()),
        name=anomaly_entity.benchmark_name,
        project_id='chromium',
        status=alert_group.AlertGroup.Status.untriaged,
        active=True,
        revision=alert_group.RevisionRange(
            repository='chromium',
            start=anomaly_entity.start_revision,
            end=anomaly_entity.end_revision,
        ),
    )
    if issue:
      group.bug = alert_group.BugInfo(
          bug_id=issue.get('id'),
          project='chromium',
      )
    if anomalies:
      group.anomalies = anomalies
    if status:
      group.status = status
    return group.put()

  def testAddAnomalies_GroupUntriaged(self):
    anomalies = [self._AddAnomaly(), self._AddAnomaly()]
    added = [self._AddAnomaly(), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        anomalies=anomalies
    )
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(name='sheriff')],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies + added),
        issue={},
    ))

    self.assertEqual(len(group.get().anomalies), 4)
    for a in added:
      self.assertIn(a, group.get().anomalies)

  def testAddAnomalies_GroupTriaged_IssueOpen(self):
    anomalies = [self._AddAnomaly(), self._AddAnomaly()]
    added = [self._AddAnomaly(), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        issue=self._issue_tracker.issue,
        anomalies=anomalies,
        status=alert_group.AlertGroup.Status.triaged,
    )
    self._issue_tracker.issue.update({
        'state': 'open',
    })
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies + added),
        issue=self._issue_tracker.issue,
    ))

    self.assertEqual(len(group.get().anomalies), 4)
    self.assertEqual(group.get().status,
                     alert_group.AlertGroup.Status.triaged)
    for a in added:
      self.assertIn(a, group.get().anomalies)
      self.assertEqual(group.get().bug.bug_id,
                       self._issue_tracker.add_comment_args[0])
      self.assertIn('Added 2 regressions to the group',
                    self._issue_tracker.add_comment_args[1])

  def testAddAnomalies_GroupTriaged_IssueClosed(self):
    anomalies = [self._AddAnomaly(), self._AddAnomaly()]
    added = [self._AddAnomaly(), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        issue=self._issue_tracker.issue,
        anomalies=anomalies,
        status=alert_group.AlertGroup.Status.closed,
    )
    self._issue_tracker.issue.update({
        'state': 'closed',
    })
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies + added),
        issue=self._issue_tracker.issue,
    ))

    self.assertEqual(len(group.get().anomalies), 4)
    self.assertEqual('open', self._issue_tracker.issue.get('state'))
    for a in added:
      self.assertIn(a, group.get().anomalies)
      self.assertEqual(group.get().bug.bug_id,
                       self._issue_tracker.add_comment_args[0])
      self.assertIn('Added 2 regressions to the group',
                    self._issue_tracker.add_comment_args[1])

  def testUpdate_GroupTriaged_IssueClosed(self):
    anomalies = [self._AddAnomaly(), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        issue=self._issue_tracker.issue,
        status=alert_group.AlertGroup.Status.triaged,
    )
    self._issue_tracker.issue.update({
        'state': 'closed',
    })
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies),
        issue=self._issue_tracker.issue,
    ))

    self.assertEqual(group.get().status, alert_group.AlertGroup.Status.closed)

  def testUpdate_GroupClosed_IssueOpen(self):
    anomalies = [self._AddAnomaly(), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        issue=self._issue_tracker.issue,
        status=alert_group.AlertGroup.Status.closed,
    )
    self._issue_tracker.issue.update({
        'state': 'open',
    })
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies),
        issue=self._issue_tracker.issue,
    ))

    self.assertEqual(group.get().status, alert_group.AlertGroup.Status.triaged)

  def testUpdate_GroupTriaged_AlertsAllRecovered(self):
    anomalies = [
        self._AddAnomaly(recovered=True),
        self._AddAnomaly(recovered=True),
    ]
    group = self._AddAlertGroup(
        anomalies[0],
        issue=self._issue_tracker.issue,
        status=alert_group.AlertGroup.Status.triaged,
    )
    self._issue_tracker.issue.update({
        'state': 'open',
    })
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies),
        issue=self._issue_tracker.issue,
    ))

    self.assertEqual('closed', self._issue_tracker.issue.get('state'))

  def testUpdate_GroupTriaged_AlertsPartRecovered(self):
    anomalies = [self._AddAnomaly(recovered=True), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        issue=self._issue_tracker.issue,
        status=alert_group.AlertGroup.Status.triaged,
    )
    self._issue_tracker.issue.update({
        'state': 'open',
    })
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies),
        issue=self._issue_tracker.issue,
    ))

    self.assertEqual('open', self._issue_tracker.issue.get('state'))

  def testTriage_GroupUntriaged(self):
    anomalies = [self._AddAnomaly(), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        status=alert_group.AlertGroup.Status.untriaged,
    )
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
        config=alert_group_workflow.AlertGroupWorkflow.Config(
            active_window=datetime.timedelta(days=7),
            triage_delay=datetime.timedelta(hours=0),
        ),
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies),
        issue=None,
    ))
    self.assertIn('2 regressions', self._issue_tracker.new_bug_args[0])

  def testTriage_GroupUntriaged_InfAnomaly(self):
    anomalies = [self._AddAnomaly(median_before_anomaly=0), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        status=alert_group.AlertGroup.Status.untriaged,
    )
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
        config=alert_group_workflow.AlertGroupWorkflow.Config(
            active_window=datetime.timedelta(days=7),
            triage_delay=datetime.timedelta(hours=0),
        ),
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies),
        issue=None,
    ))
    self.assertIn('inf', self._issue_tracker.new_bug_args[1])

  def testTriage_GroupTriaged_InfAnomaly(self):
    anomalies = [self._AddAnomaly(median_before_anomaly=0), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        issue=self._issue_tracker.issue,
        status=alert_group.AlertGroup.Status.triaged,
    )
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies),
        issue=self._issue_tracker.issue,
    ))
    self.assertIn('inf', self._issue_tracker.add_comment_args[1])

  def testArchive_GroupUntriaged(self):
    anomalies = [self._AddAnomaly(), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        anomalies=anomalies,
        status=alert_group.AlertGroup.Status.untriaged,
    )
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(name='sheriff')],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
        config=alert_group_workflow.AlertGroupWorkflow.Config(
            active_window=datetime.timedelta(days=0),
            triage_delay=datetime.timedelta(hours=0),
        ),
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies),
        issue=None,
    ))
    self.assertEqual(False, group.get().active)

  def testArchive_GroupTriaged(self):
    anomalies = [self._AddAnomaly(), self._AddAnomaly()]
    group = self._AddAlertGroup(
        anomalies[0],
        anomalies=anomalies,
        issue=self._issue_tracker.issue,
        status=alert_group.AlertGroup.Status.triaged,
    )
    self._issue_tracker.issue.update({
        'state': 'open',
    })
    self._sheriff_config.patterns = {
        '*': [subscription.Subscription(
            name='sheriff', auto_triage_enable=True)],
    }
    w = alert_group_workflow.AlertGroupWorkflow(
        group.get(),
        sheriff_config=self._sheriff_config,
        issue_tracker=self._issue_tracker,
        config=alert_group_workflow.AlertGroupWorkflow.Config(
            active_window=datetime.timedelta(days=0),
            triage_delay=datetime.timedelta(hours=0),
        ),
    )
    w.Process(update=alert_group_workflow.AlertGroupWorkflow.GroupUpdate(
        now=datetime.datetime.utcnow(),
        anomalies=ndb.get_multi(anomalies),
        issue=self._issue_tracker.issue,
    ))
    self.assertEqual(True, group.get().active)
