-- 仅结构参考，无用户行；初始化使用迁移，不向已有库导入。
-- MySQL dump 10.13  Distrib 8.4.11, for Win64 (x86_64)
--
-- Host: 127.0.0.1    Database: study_review_dev
-- ------------------------------------------------------
-- Server version	8.4.11

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `ai_gateway_account`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_gateway_account` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `budget_cny` decimal(14,6) NOT NULL,
  `spent_cny` decimal(14,6) NOT NULL,
  `reserved_cny` decimal(14,6) NOT NULL,
  `revision` bigint unsigned NOT NULL,
  `key_reference` char(32) DEFAULT NULL,
  `enabled` tinyint(1) NOT NULL,
  `consent_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `owner_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `owner_id` (`owner_id`),
  CONSTRAINT `ai_gateway_account_owner_id_d9783bb6_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`),
  CONSTRAINT `ai_account_amounts_nonnegative` CHECK (((`budget_cny` >= 0) and (`reserved_cny` >= 0) and (`spent_cny` >= 0))),
  CONSTRAINT `ai_account_enabled_consent` CHECK (((`enabled` = 0x00) or ((`budget_cny` > 0) and (`consent_at` is not null) and (`key_reference` is not null)))),
  CONSTRAINT `ai_gateway_account_chk_1` CHECK ((`revision` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ai_gateway_messagecontext`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_gateway_messagecontext` (
  `message_id` char(32) NOT NULL,
  `selected_history_ids` json NOT NULL,
  `selected_target_snapshot` json NOT NULL,
  `selected_course_snapshot` json NOT NULL,
  `expected_version` longtext NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `owner_id` int NOT NULL,
  PRIMARY KEY (`message_id`),
  KEY `ai_gateway_messagecontext_owner_id_c6abb90d_fk_auth_user_id` (`owner_id`),
  CONSTRAINT `ai_gateway_messageco_message_id_5c7d3f31_fk_assistant` FOREIGN KEY (`message_id`) REFERENCES `assistant_message` (`id`),
  CONSTRAINT `ai_gateway_messagecontext_owner_id_c6abb90d_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ai_gateway_requestledger`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_gateway_requestledger` (
  `id` char(32) NOT NULL,
  `request_id` char(32) NOT NULL,
  `request_hash` varchar(64) NOT NULL,
  `state` varchar(9) NOT NULL,
  `dispatched` tinyint(1) NOT NULL,
  `dispatched_at` datetime(6) DEFAULT NULL,
  `pricing_snapshot` json NOT NULL,
  `input_token_ceiling` int unsigned NOT NULL,
  `output_token_ceiling` int unsigned NOT NULL,
  `reserved_cny` decimal(14,6) NOT NULL,
  `held_cny` decimal(14,6) NOT NULL,
  `estimated_cost_cny_peak` decimal(14,6) DEFAULT NULL,
  `usage` json DEFAULT NULL,
  `failure_code` varchar(60) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `settled_at` datetime(6) DEFAULT NULL,
  `account_id` bigint NOT NULL,
  `owner_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `request_id` (`request_id`),
  KEY `ai_ledger_owner_state_time` (`owner_id`,`state`,`created_at`),
  KEY `ai_gateway_requestle_account_id_9ed857a5_fk_ai_gatewa` (`account_id`),
  CONSTRAINT `ai_gateway_requestle_account_id_9ed857a5_fk_ai_gatewa` FOREIGN KEY (`account_id`) REFERENCES `ai_gateway_account` (`id`),
  CONSTRAINT `ai_gateway_requestledger_owner_id_d96fa3a3_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`),
  CONSTRAINT `ai_gateway_requestledger_chk_1` CHECK ((`input_token_ceiling` >= 0)),
  CONSTRAINT `ai_gateway_requestledger_chk_2` CHECK ((`output_token_ceiling` >= 0)),
  CONSTRAINT `ai_ledger_amounts_nonnegative` CHECK (((`held_cny` >= 0) and (`reserved_cny` >= 0) and ((`estimated_cost_cny_peak` is null) or (`estimated_cost_cny_peak` >= 0)))),
  CONSTRAINT `ai_ledger_dispatch_consistent` CHECK ((((`dispatched` = 0x00) and (`dispatched_at` is null)) or ((`dispatched` = 0x01) and (`dispatched_at` is not null)))),
  CONSTRAINT `ai_ledger_state_valid` CHECK ((`state` in (_utf8mb4'reserved',_utf8mb4'succeeded',_utf8mb4'failed',_utf8mb4'uncertain')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `assistant_chatsession`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `assistant_chatsession` (
  `id` char(32) NOT NULL,
  `title` varchar(120) NOT NULL,
  `submission_key` char(32) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `owner_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `submission_key` (`submission_key`),
  KEY `assist_session_owner_time` (`owner_id`,`updated_at`),
  CONSTRAINT `assistant_chatsession_owner_id_b7ba825d_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `assistant_draft`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `assistant_draft` (
  `id` char(32) NOT NULL,
  `operation` varchar(20) NOT NULL,
  `title` varchar(180) NOT NULL,
  `payload` json NOT NULL,
  `before_snapshot` json NOT NULL,
  `after_snapshot` json NOT NULL,
  `target_id` bigint unsigned DEFAULT NULL,
  `expected_version` longtext NOT NULL,
  `submission_key` char(32) NOT NULL,
  `request_hash` varchar(64) NOT NULL,
  `status` varchar(7) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `expires_at` datetime(6) NOT NULL,
  `applied_at` datetime(6) DEFAULT NULL,
  `applied_object_id` bigint unsigned DEFAULT NULL,
  `confirmation_key` char(32) DEFAULT NULL,
  `owner_id` int NOT NULL,
  `session_id` char(32) NOT NULL,
  `source_message_id` char(32) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `submission_key` (`submission_key`),
  UNIQUE KEY `confirmation_key` (`confirmation_key`),
  KEY `assist_draft_owner_status` (`owner_id`,`status`,`created_at`),
  KEY `assistant_draft_session_id_8021a2c7_fk_assistant_chatsession_id` (`session_id`),
  KEY `assistant_draft_source_message_id_2f95b77e_fk_assistant` (`source_message_id`),
  CONSTRAINT `assistant_draft_owner_id_c70e8abb_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`),
  CONSTRAINT `assistant_draft_session_id_8021a2c7_fk_assistant_chatsession_id` FOREIGN KEY (`session_id`) REFERENCES `assistant_chatsession` (`id`),
  CONSTRAINT `assistant_draft_source_message_id_2f95b77e_fk_assistant` FOREIGN KEY (`source_message_id`) REFERENCES `assistant_message` (`id`),
  CONSTRAINT `assist_draft_application_valid` CHECK ((((`applied_at` is null) and (`applied_object_id` is null) and (`confirmation_key` is null) and (`status` = _utf8mb4'pending')) or ((`applied_at` is not null) and (`applied_object_id` is not null) and (`confirmation_key` is not null) and (`status` = _utf8mb4'applied')))),
  CONSTRAINT `assist_draft_operation_valid` CHECK ((`operation` in (_utf8mb4'create_question',_utf8mb4'update_question',_utf8mb4'update_task'))),
  CONSTRAINT `assistant_draft_chk_1` CHECK ((`target_id` >= 0)),
  CONSTRAINT `assistant_draft_chk_2` CHECK ((`applied_object_id` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `assistant_message`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `assistant_message` (
  `id` char(32) NOT NULL,
  `role` varchar(9) NOT NULL,
  `text` longtext NOT NULL,
  `status` varchar(16) NOT NULL,
  `submission_key` char(32) NOT NULL,
  `request_hash` varchar(64) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `reply_to_id` char(32) DEFAULT NULL,
  `session_id` char(32) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `submission_key` (`submission_key`),
  UNIQUE KEY `reply_to_id` (`reply_to_id`),
  KEY `assist_message_session_time` (`session_id`,`created_at`),
  CONSTRAINT `assistant_message_reply_to_id_928b94b9_fk_assistant_message_id` FOREIGN KEY (`reply_to_id`) REFERENCES `assistant_message` (`id`),
  CONSTRAINT `assistant_message_session_id_823a2e09_fk_assistant` FOREIGN KEY (`session_id`) REFERENCES `assistant_chatsession` (`id`),
  CONSTRAINT `assist_message_role_valid` CHECK ((`role` in (_utf8mb4'user',_utf8mb4'assistant',_utf8mb4'system'))),
  CONSTRAINT `assist_message_status_valid` CHECK ((`status` in (_utf8mb4'saved',_utf8mb4'processing',_utf8mb4'completed',_utf8mb4'not_connected',_utf8mb4'provider_error')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `assistant_messageattachment`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `assistant_messageattachment` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `position` smallint unsigned NOT NULL,
  `attachment_id` char(32) NOT NULL,
  `message_id` char(32) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `assist_message_attachment_uq` (`message_id`,`attachment_id`),
  KEY `assistant_messageatt_attachment_id_110ea37d_fk_attachmen` (`attachment_id`),
  CONSTRAINT `assistant_messageatt_attachment_id_110ea37d_fk_attachmen` FOREIGN KEY (`attachment_id`) REFERENCES `attachments_attachment` (`id`),
  CONSTRAINT `assistant_messageatt_message_id_83630f7e_fk_assistant` FOREIGN KEY (`message_id`) REFERENCES `assistant_message` (`id`),
  CONSTRAINT `assistant_messageattachment_chk_1` CHECK ((`position` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `attachments_attachment`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `attachments_attachment` (
  `id` char(32) NOT NULL,
  `display_name` varchar(200) NOT NULL,
  `width` int unsigned NOT NULL,
  `height` int unsigned NOT NULL,
  `sha256` varchar(64) NOT NULL,
  `storage_key` varchar(80) NOT NULL,
  `byte_size` bigint unsigned NOT NULL,
  `thumbnail_bytes` int unsigned NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `owner_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `storage_key` (`storage_key`),
  UNIQUE KEY `attachment_owner_sha_uq` (`owner_id`,`sha256`),
  KEY `attachment_owner_time_idx` (`owner_id`,`created_at`),
  CONSTRAINT `attachments_attachment_owner_id_720defb8_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`),
  CONSTRAINT `attachment_dimensions_valid` CHECK (((`height` >= 1) and (`height` <= 10000) and (`width` >= 1) and (`width` <= 10000))),
  CONSTRAINT `attachments_attachment_chk_1` CHECK ((`width` >= 0)),
  CONSTRAINT `attachments_attachment_chk_2` CHECK ((`height` >= 0)),
  CONSTRAINT `attachments_attachment_chk_3` CHECK ((`byte_size` >= 0)),
  CONSTRAINT `attachments_attachment_chk_4` CHECK ((`thumbnail_bytes` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `att_image_no_update` BEFORE UPDATE ON `attachments_attachment` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Image history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `att_image_no_delete` BEFORE DELETE ON `attachments_attachment` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Image history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `attachments_questionimage`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `attachments_questionimage` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `role` varchar(16) NOT NULL,
  `position` smallint unsigned NOT NULL,
  `attachment_id` char(32) NOT NULL,
  `question_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `question_image_position_uq` (`question_id`,`role`,`position`),
  UNIQUE KEY `question_image_attachment_uq` (`question_id`,`role`,`attachment_id`),
  KEY `attachments_question_attachment_id_31d2c34f_fk_attachmen` (`attachment_id`),
  CONSTRAINT `attachments_question_attachment_id_31d2c34f_fk_attachmen` FOREIGN KEY (`attachment_id`) REFERENCES `attachments_attachment` (`id`),
  CONSTRAINT `attachments_question_question_id_a5ee41c3_fk_learning_` FOREIGN KEY (`question_id`) REFERENCES `learning_wrongquestion` (`id`),
  CONSTRAINT `attachments_questionimage_chk_1` CHECK ((`position` >= 0)),
  CONSTRAINT `question_image_role_valid` CHECK ((`role` in (_utf8mb4'question',_utf8mb4'original_answer',_utf8mb4'correct_answer',_utf8mb4'error_reason')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `attachments_reviewimagemanifest`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `attachments_reviewimagemanifest` (
  `review_id` bigint NOT NULL,
  `image_count` smallint unsigned NOT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`review_id`),
  CONSTRAINT `attachments_reviewim_review_id_3a52de41_fk_learning_` FOREIGN KEY (`review_id`) REFERENCES `learning_reviewrecord` (`id`),
  CONSTRAINT `attachments_reviewimagemanifest_chk_1` CHECK ((`image_count` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `att_manifest_no_update` BEFORE UPDATE ON `attachments_reviewimagemanifest` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Image history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `att_manifest_no_delete` BEFORE DELETE ON `attachments_reviewimagemanifest` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Image history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `attachments_reviewimagesnapshot`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `attachments_reviewimagesnapshot` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `role` varchar(16) NOT NULL,
  `position` smallint unsigned NOT NULL,
  `name_snapshot` varchar(200) NOT NULL,
  `width_snapshot` int unsigned NOT NULL,
  `height_snapshot` int unsigned NOT NULL,
  `sha256_snapshot` varchar(64) NOT NULL,
  `attachment_id` char(32) NOT NULL,
  `review_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `review_image_position_uq` (`review_id`,`role`,`position`),
  UNIQUE KEY `review_image_attachment_uq` (`review_id`,`role`,`attachment_id`),
  KEY `attachments_reviewim_attachment_id_915a5449_fk_attachmen` (`attachment_id`),
  CONSTRAINT `attachments_reviewim_attachment_id_915a5449_fk_attachmen` FOREIGN KEY (`attachment_id`) REFERENCES `attachments_attachment` (`id`),
  CONSTRAINT `attachments_reviewim_review_id_135bb2aa_fk_learning_` FOREIGN KEY (`review_id`) REFERENCES `learning_reviewrecord` (`id`),
  CONSTRAINT `attachments_reviewimagesnapshot_chk_1` CHECK ((`position` >= 0)),
  CONSTRAINT `attachments_reviewimagesnapshot_chk_2` CHECK ((`width_snapshot` >= 0)),
  CONSTRAINT `attachments_reviewimagesnapshot_chk_3` CHECK ((`height_snapshot` >= 0)),
  CONSTRAINT `review_image_role_valid` CHECK ((`role` in (_utf8mb4'question',_utf8mb4'original_answer',_utf8mb4'correct_answer',_utf8mb4'error_reason')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `att_snapshot_no_update` BEFORE UPDATE ON `attachments_reviewimagesnapshot` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Image history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `att_snapshot_no_delete` BEFORE DELETE ON `attachments_reviewimagesnapshot` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Image history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `auth_group`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_group` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(150) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_group_permissions`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_group_permissions` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `group_id` int NOT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` (`group_id`,`permission_id`),
  KEY `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` (`permission_id`),
  CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_permission`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_permission` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `content_type_id` int NOT NULL,
  `codename` varchar(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_permission_content_type_id_codename_01ab375a_uniq` (`content_type_id`,`codename`),
  CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_user`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_user` (
  `id` int NOT NULL AUTO_INCREMENT,
  `password` varchar(128) NOT NULL,
  `last_login` datetime(6) DEFAULT NULL,
  `is_superuser` tinyint(1) NOT NULL,
  `username` varchar(150) NOT NULL,
  `first_name` varchar(150) NOT NULL,
  `last_name` varchar(150) NOT NULL,
  `email` varchar(254) NOT NULL,
  `is_staff` tinyint(1) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `date_joined` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_user_groups`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_user_groups` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `group_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_user_groups_user_id_group_id_94350c0c_uniq` (`user_id`,`group_id`),
  KEY `auth_user_groups_group_id_97559544_fk_auth_group_id` (`group_id`),
  CONSTRAINT `auth_user_groups_group_id_97559544_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`),
  CONSTRAINT `auth_user_groups_user_id_6a12ed8b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_user_user_permissions`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_user_user_permissions` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_user_user_permissions_user_id_permission_id_14a6b632_uniq` (`user_id`,`permission_id`),
  KEY `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm` (`permission_id`),
  CONSTRAINT `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `django_content_type`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_content_type` (
  `id` int NOT NULL AUTO_INCREMENT,
  `app_label` varchar(100) NOT NULL,
  `model` varchar(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `django_content_type_app_label_model_76bd3d3b_uniq` (`app_label`,`model`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `django_migrations`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_migrations` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `app` varchar(255) NOT NULL,
  `name` varchar(255) NOT NULL,
  `applied` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `django_session`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_session` (
  `session_key` varchar(40) NOT NULL,
  `session_data` longtext NOT NULL,
  `expire_date` datetime(6) NOT NULL,
  PRIMARY KEY (`session_key`),
  KEY `django_session_expire_date_a5c62663` (`expire_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `learning_course`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `learning_course` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(120) NOT NULL,
  `description` longtext NOT NULL,
  `is_archived` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `owner_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `course_owner_name_uq` (`owner_id`,`name`),
  KEY `course_owner_archive_idx` (`owner_id`,`is_archived`),
  CONSTRAINT `learning_course_owner_id_cb4ea5b1_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `learning_knowledgepoint`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `learning_knowledgepoint` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(120) NOT NULL,
  `course_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `point_course_name_uq` (`course_id`,`name`),
  CONSTRAINT `learning_knowledgepoint_course_id_0b09b9f2_fk_learning_course_id` FOREIGN KEY (`course_id`) REFERENCES `learning_course` (`id`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `study_knowledgepoint_no_move` BEFORE UPDATE ON `learning_knowledgepoint` FOR EACH ROW BEGIN
          IF OLD.course_id <> NEW.course_id THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Moving content between courses is not supported';
          END IF;
        END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `learning_questionknowledgepoint`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `learning_questionknowledgepoint` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `knowledge_point_id` bigint NOT NULL,
  `question_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `question_point_uq` (`question_id`,`knowledge_point_id`),
  KEY `learning_questionkno_knowledge_point_id_b798035b_fk_learning_` (`knowledge_point_id`),
  CONSTRAINT `learning_questionkno_knowledge_point_id_b798035b_fk_learning_` FOREIGN KEY (`knowledge_point_id`) REFERENCES `learning_knowledgepoint` (`id`),
  CONSTRAINT `learning_questionkno_question_id_9ba01b16_fk_learning_` FOREIGN KEY (`question_id`) REFERENCES `learning_wrongquestion` (`id`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `study_point_same_course_insert` BEFORE INSERT ON `learning_questionknowledgepoint` FOR EACH ROW BEGIN
          IF (SELECT course_id FROM learning_wrongquestion WHERE id=NEW.question_id) <>
             (SELECT course_id FROM learning_knowledgepoint WHERE id=NEW.knowledge_point_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Knowledge point must belong to the same course';
          END IF;
        END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `study_point_same_course_update` BEFORE UPDATE ON `learning_questionknowledgepoint` FOR EACH ROW BEGIN
          IF (SELECT course_id FROM learning_wrongquestion WHERE id=NEW.question_id) <>
             (SELECT course_id FROM learning_knowledgepoint WHERE id=NEW.knowledge_point_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Knowledge point must belong to the same course';
          END IF;
        END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `learning_reviewrecord`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `learning_reviewrecord` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `reviewed_at` datetime(6) NOT NULL,
  `review_date` date NOT NULL,
  `answer` longtext NOT NULL,
  `rating` varchar(5) NOT NULL,
  `note` longtext NOT NULL,
  `next_review_date` date NOT NULL,
  `title_snapshot` varchar(180) NOT NULL,
  `question_snapshot` longtext NOT NULL,
  `original_answer_snapshot` longtext NOT NULL,
  `correct_answer_snapshot` longtext NOT NULL,
  `error_reason_snapshot` longtext NOT NULL,
  `course_snapshot` varchar(120) NOT NULL,
  `knowledge_points_snapshot` json NOT NULL,
  `submission_key` char(32) NOT NULL,
  `question_id` bigint NOT NULL,
  `is_example` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `submission_key` (`submission_key`),
  KEY `review_question_date_idx` (`question_id`,`review_date`),
  CONSTRAINT `learning_reviewrecor_question_id_d77d20e1_fk_learning_` FOREIGN KEY (`question_id`) REFERENCES `learning_wrongquestion` (`id`),
  CONSTRAINT `review_next_after_today` CHECK ((`next_review_date` > `review_date`)),
  CONSTRAINT `review_rating_valid` CHECK ((`rating` in (_utf8mb4'again',_utf8mb4'hard',_utf8mb4'good')))
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `study_review_no_update` BEFORE UPDATE ON `learning_reviewrecord` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Review history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `study_review_no_delete` BEFORE DELETE ON `learning_reviewrecord` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Review history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `learning_task`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `learning_task` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `title` varchar(180) NOT NULL,
  `description` longtext NOT NULL,
  `due_date` date NOT NULL,
  `status` varchar(4) NOT NULL,
  `completed_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `creation_key` char(32) NOT NULL,
  `course_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `creation_key` (`creation_key`),
  KEY `task_course_status_due_idx` (`course_id`,`status`,`due_date`),
  CONSTRAINT `learning_task_course_id_96b7ebaa_fk_learning_course_id` FOREIGN KEY (`course_id`) REFERENCES `learning_course` (`id`),
  CONSTRAINT `task_completion_consistent` CHECK ((((`completed_at` is null) and (`status` = _utf8mb4'todo')) or ((`completed_at` is not null) and (`status` = _utf8mb4'done'))))
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `study_task_no_move` BEFORE UPDATE ON `learning_task` FOR EACH ROW BEGIN
          IF OLD.course_id <> NEW.course_id THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Moving content between courses is not supported';
          END IF;
        END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `learning_wrongquestion`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `learning_wrongquestion` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `title` varchar(180) NOT NULL,
  `content` longtext NOT NULL,
  `original_answer` longtext NOT NULL,
  `correct_answer` longtext NOT NULL,
  `error_reason` longtext NOT NULL,
  `next_review_date` date NOT NULL,
  `is_archived` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `creation_key` char(32) NOT NULL,
  `course_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `creation_key` (`creation_key`),
  KEY `question_course_due_idx` (`course_id`,`is_archived`,`next_review_date`),
  CONSTRAINT `learning_wrongquestion_course_id_b5ac6fec_fk_learning_course_id` FOREIGN KEY (`course_id`) REFERENCES `learning_course` (`id`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `study_wrongquestion_no_move` BEFORE UPDATE ON `learning_wrongquestion` FOR EACH ROW BEGIN
          IF OLD.course_id <> NEW.course_id THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Moving content between courses is not supported';
          END IF;
        END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `scheduling_scheduleevent`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `scheduling_scheduleevent` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `algorithm` varchar(16) NOT NULL,
  `algorithm_version` varchar(20) NOT NULL,
  `config_version` varchar(40) NOT NULL,
  `config_snapshot` json NOT NULL,
  `state_revision_before` bigint unsigned NOT NULL,
  `state_revision_after` bigint unsigned NOT NULL,
  `before_state` json NOT NULL,
  `after_state` json NOT NULL,
  `fsrs_review_log` json NOT NULL,
  `reviewed_at` datetime(6) NOT NULL,
  `review_date` date NOT NULL,
  `due_utc` datetime(6) NOT NULL,
  `suggested_date` date NOT NULL,
  `applied_date` date NOT NULL,
  `manual_override_date` date DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `review_record_id` bigint NOT NULL,
  `state_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `review_record_id` (`review_record_id`),
  KEY `schedule_event_time_idx` (`state_id`,`reviewed_at`),
  CONSTRAINT `scheduling_schedulee_review_record_id_1c516d3b_fk_learning_` FOREIGN KEY (`review_record_id`) REFERENCES `learning_reviewrecord` (`id`),
  CONSTRAINT `scheduling_schedulee_state_id_8db73982_fk_schedulin` FOREIGN KEY (`state_id`) REFERENCES `scheduling_schedulingstate` (`id`),
  CONSTRAINT `schedule_applied_future` CHECK ((`applied_date` > `review_date`)),
  CONSTRAINT `schedule_due_after_review` CHECK ((`due_utc` > `reviewed_at`)),
  CONSTRAINT `schedule_override_consistent` CHECK ((((`applied_date` = `suggested_date`) and (`manual_override_date` is null)) or ((`manual_override_date` = `applied_date`) and (`manual_override_date` is not null)))),
  CONSTRAINT `schedule_revision_increments` CHECK ((`state_revision_after` = (`state_revision_before` + 1))),
  CONSTRAINT `schedule_suggestion_future` CHECK ((`suggested_date` > `review_date`)),
  CONSTRAINT `scheduling_scheduleevent_chk_1` CHECK ((`state_revision_before` >= 0)),
  CONSTRAINT `scheduling_scheduleevent_chk_2` CHECK ((`state_revision_after` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `study_schedule_no_update` BEFORE UPDATE ON `scheduling_scheduleevent` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Scheduling history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 */ /*!50003 TRIGGER `study_schedule_no_delete` BEFORE DELETE ON `scheduling_scheduleevent` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Scheduling history is immutable' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `scheduling_schedulingstate`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `scheduling_schedulingstate` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `algorithm` varchar(16) NOT NULL,
  `algorithm_version` varchar(20) NOT NULL,
  `config_version` varchar(40) NOT NULL,
  `config_snapshot` json NOT NULL,
  `card_state` json NOT NULL,
  `revision` bigint unsigned NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `question_id` bigint NOT NULL,
  `user_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `schedule_user_question_uq` (`user_id`,`question_id`),
  KEY `scheduling_schedulin_question_id_06d8c1ab_fk_learning_` (`question_id`),
  CONSTRAINT `scheduling_schedulin_question_id_06d8c1ab_fk_learning_` FOREIGN KEY (`question_id`) REFERENCES `learning_wrongquestion` (`id`),
  CONSTRAINT `scheduling_schedulingstate_user_id_c481762c_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`),
  CONSTRAINT `scheduling_schedulingstate_chk_1` CHECK ((`revision` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping events for database 'study_review_dev'
--

--
-- Dumping routines for database 'study_review_dev'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed
