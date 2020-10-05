#!/usr/bin/env python3

import math
import rospy
import oyaml as yaml
import tf
import smach
import smach_ros
from geometry_msgs.msg import PoseStamped
import mission_plan

class MissionPlanner():
    def __init__(self, yaml_file_path):
        self.yaml_file_path = yaml_file_path

        self.readMissionsData()
        self.main()

    def readMissionsData(self):
        with open(self.yaml_file_path, 'r') as file:
            self.missions_data = yaml.load(file)

    def main(self):
        rospy.init_node('mission_planner_node')
        rospy.loginfo("Misison planner started.")

        rospy.loginfo(self.missions_data)

        # Setup state machine.
        state_machine = mission_plan.createMissionPlan(self.missions_data)

        # Create and start the introspection server.
        introspection_server = smach_ros.IntrospectionServer('mission_planner_introspection_server', state_machine, '/mission_planner')
        introspection_server.start()

        # Execute state machine.
        outcome = state_machine.execute()
        rospy.loginfo("Mission plan terminated with outcome '" + outcome + "'.")

        # Wait for ctrl-c to stop the application
        introspection_server.stop()
        

class Mission(smach.State):
    def __init__(self, mission_data):
        smach.State.__init__(self, outcomes=['Completed', 'Aborted', 'Next Goal'])
        self.mission_data = mission_data
        self.goal_idx = 0
        self.pose_publisher = rospy.Publisher('/move_base_simple/goal', PoseStamped, queue_size=10)
        self.pose_subscriber = rospy.Subscriber('/base_pose_measured', PoseStamped, self.poseCallback)

        self.distance_to_goal_tolerance_m = 0.3
        self.angle_to_goal_tolerance_rad = 0.7

    def execute(self, userdata):
        if(self.goal_idx >= len(self.mission_data.keys())):
            rospy.loginfo("No more goals left in this mission.")
            self.goal_idx = 0
            return 'Completed'

        current_goal_name = self.mission_data.keys()[self.goal_idx]
        current_goal = self.mission_data[current_goal_name]

        self.setGoal(current_goal['x_m'], current_goal['y_m'], current_goal['yaw_rad'])
        rospy.loginfo("Goal set: '" + current_goal_name + "'.")

        countdown_s = 4
        while countdown_s:
            if(self.reachedGoalWithTolerance()):
                rospy.loginfo("Goal reached before countdown ended. Loading next goal...")
                self.goal_idx += 1
                return 'Next Goal'
            else:
                rospy.loginfo(str(countdown_s) + "s left until skipping current goal.")
                rospy.sleep(1)
            countdown_s -= 1
        rospy.logwarn("Countdown ended without reaching current goal.")
        if(self.goal_idx == 0):
            rospy.logwarn("Starting goal of mission unreachable. Aborting mission...")
            self.goal_idx = 0.
            return 'Aborted'
        else:
            rospy.logwarn("Skipping current goal...")
            self.goal_idx += 1
            return 'Next Goal'

    def setGoal(self, x_m, y_m, yaw_rad):
        quaternion = tf.transformations.quaternion_from_euler(0., 0., yaw_rad)

        pose_stamped_msg = PoseStamped()
        pose_stamped_msg.header.seq = 0
        pose_stamped_msg.header.stamp.secs = rospy.get_rostime().secs
        pose_stamped_msg.header.stamp.nsecs = rospy.get_rostime().nsecs
        pose_stamped_msg.header.frame_id = "world"
        pose_stamped_msg.pose.position.x = x_m
        pose_stamped_msg.pose.position.y = y_m
        pose_stamped_msg.pose.position.z = 0.
        pose_stamped_msg.pose.orientation.x = quaternion[0]
        pose_stamped_msg.pose.orientation.y = quaternion[1]
        pose_stamped_msg.pose.orientation.z = quaternion[2]
        pose_stamped_msg.pose.orientation.w = quaternion[3]
        self.pose_publisher.publish(pose_stamped_msg)

        self.goal_x_m = x_m
        self.goal_y_m = y_m
        self.goal_yaw_rad = yaw_rad

    def poseCallback(self, pose_stamped_msg):
        rospy.loginfo_once("Estimated base pose received.")

        x_m = pose_stamped_msg.pose.position.x
        y_m = pose_stamped_msg.pose.position.y
        quaternion = pose_stamped_msg.pose.orientation
        explicit_quat = [quaternion.x, quaternion.y, quaternion.z, quaternion.w]
        roll_rad, pitch_rad, yaw_rad = tf.transformations.euler_from_quaternion(explicit_quat)

        self.estimated_x_m = x_m
        self.estimated_y_m = y_m
        self.estimated_yaw_rad = yaw_rad

    def reachedGoalWithTolerance(self):
        try:
            distance_to_goal = math.sqrt(pow(self.goal_x_m - self.estimated_x_m, 2) + pow(self.goal_y_m - self.estimated_y_m, 2))
            angle_to_goal = abs(self.goal_yaw_rad - self.estimated_yaw_rad)
            distance_to_goal_satisfied = (distance_to_goal <= self.distance_to_goal_tolerance_m)
            angle_to_goal_satisfied = (angle_to_goal <= self.angle_to_goal_tolerance_rad)

            return distance_to_goal_satisfied and angle_to_goal_satisfied
        except:
            rospy.logwarn("No estimated base pose received yet.")
            return False;
