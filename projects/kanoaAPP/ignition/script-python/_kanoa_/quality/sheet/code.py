################################################################################
def copySheet(copyShtInfo, userId):
	"""
		Makes a copy of a checksheet
		Args:
			copyShtInfo (dict)
			 - chkShtId (int): Check sheet to copy
			 - chkShtName (string): Name of new Check sheet. If None we will add a numeric suffix
			userId (int)
		Returns:
			newChkShtId (int)
			message (string)
		Updated:
			jfc 12/26/23: Refactored
			jfc 01/20/24: Updated to return new chkShtId
			jfc 02/01/24: Fixed getChecks() call
			JZ  07/24/24: fixed function calls
			jfc 08/20/25: Now passes in name of new checksheet and returns a tuple
			JZ  11/24/25: need to remap trigger ID's when copying trigger check ID references
			jfc 12/11/25: Updated logic for determining next chkShtName in sequence.
			jfc 12/31/25: Fixed issue with triggers
			jfc 04/07/26: Copy over images
	"""

	def nextNumberForPrefix(strings, prefix, start):
		''''
		Consider only items matching the given prefix, optionally followed by a number.
		Returns max number + 1 for that prefix; otherwise `start`.
		'''
		# Example match: \"Box Line\", \"Box Line 7\", \"Box Line   42\"
		pattern = re.compile(r'^\s*' + re.escape(prefix) + r'(?:\s+(\d+))?\s*$', re.IGNORECASE)
	
		nums = []
		for s in strings:
			if s is None: continue
			m = pattern.match(s)
			if m and m.group(1): nums.append(int(m.group(1)))
		return (max(nums) + 1) if nums else start
	
	def getNewChkShtName(chkShtPath):
		'''
		This function figures out what we are going to call the new check sheet, by looking at all check sheets in this grouping
		'''
			
		chkShtName = chkShtPath.split('\\')[-1]
		basePrefix = re.sub(r'\s*\d+\s*$', '', chkShtName).strip()
		cleanedChkShtPath = re.sub(r'\d+$', '', chkShtPath).rstrip() # Remove trailing number and extra spaces
		numElements = len(chkShtPath.split('\\'))
	
		hasSpace = bool(re.search(r'\s+\d+$', chkShtName.strip())) # Check if the current_name already has a space before the number
	
		paramsDict = {'path': cleanedChkShtPath + '%'}
		data = system.kanoa.utilities.convertDatasetToDict(system.kanoa.quality.sheet.getSheets(paramsDict), 'path', None)
	
		chkShtNameList = []
		for k,v in data.items():
			if len(k.split('\\')) == numElements: chkShtNameList.append(str(v['chkShtName']))
	
		return "%s%s%s"%(basePrefix, ' ' if hasSpace else '', str(nextNumberForPrefix(chkShtNameList, basePrefix, 1)))

	dbName = system.kanoa.config.getDBName('QDS')
	log = system.util.getLogger("kanoa_quality")
	log.info("copySheet() called with %s by %s"%(copyShtInfo, userId))

	data = system.kanoa.quality.sheet.getSheets({'chkShtId':copyShtInfo['chkShtId']})	
	if data.rowCount == 0: 	return None, 'Check sheet not found'
	
	import java.lang
	import re
	
	try:
		chkShtInfo = system.kanoa.utilities.convertDatasetRowToJSON(data, 0)
		chkItemTriggerDict = {}
		chkShtInfo['enabled'] = False
				
		chkShtName = copyShtInfo['chkShtName'] if copyShtInfo.has_key('chkShtName') and copyShtInfo['chkShtName'] else getNewChkShtName(chkShtInfo['path'])

		chkShtInfo['chkShtName'] = chkShtName
		newChkShtId, msg = system.kanoa.quality.sheet.addSheet(chkShtInfo, userId)
		log.info("addSheet() returned %s %s"%(newChkShtId, msg))
		if newChkShtId is None:
			log.error("addSheet failed with %s"%msg)
			return None, msg
	
		log.info('copying checksheet triggers')
		triggers = system.kanoa.utilities.convertDatasetToJSON(system.kanoa.quality.config.getChkShtTriggers({'chkShtId':chkShtInfo['chkShtId']}))
		for row in triggers:
			row['chkShtId'] = newChkShtId
			chkShtTriggerId = system.kanoa.quality.config.addChkShtTrigger(row, userId)
		
		log.info('copying checksheet groups')
		groups = system.kanoa.utilities.convertDatasetToJSON(system.kanoa.quality.config.getGroups({'chkShtId': chkShtInfo['chkShtId']}))
		for row in groups:
			row['chkShtId'] = newChkShtId
			log.info('Adding new chkItem group %s '%row['chkItemGroupName'])
			newGrpId = system.kanoa.quality.config.addGroup(row, userId)
			if newGrpId is None:
				log.error("Invalid checkItemGroup")
				return
			log.info('chkItem group %s created '%newGrpId)				
			
			log.info('copying %s checkItems'%row['chkItemGroupName'])
			checks = system.kanoa.utilities.convertDatasetToJSON(system.kanoa.quality.config.getChecks({'chkItemGroupId': row['chkItemGroupId'] or -1}))
			
			chkItemDict = {}
			for chkRow in checks:
				chkRow['chkShtId'] = newChkShtId
				chkRow['chkItemGroupId'] = newGrpId
				if chkRow['chkItemTriggerId'] is not None and chkItemTriggerDict.has_key(chkRow['chkItemTriggerId']): chkRow['chkItemTriggerId'] = chkItemTriggerDict[chkRow['chkItemTriggerId']]
				log.info('Adding checkItem %s'%chkRow['chkItemName'])
				newChkItemId = system.kanoa.quality.config.addCheck(chkRow, userId)
				if chkRow['chkItemTypeName'] == 'Trigger': chkItemTriggerDict[chkRow['chkItemId']] = newChkItemId
				chkItemDict[chkRow['chkItemId']] = newChkItemId
	
		itemIds = [row['itemId'] for row in system.kanoa.quality.sheet.getItems(chkShtInfo['chkShtId'])]
		if len(itemIds) > 0:
			log.info('adding checksheet items %s'%itemIds)
			system.kanoa.quality.sheet.addItems(newChkShtId, itemIds, userId)
		
		itemClassIds = [row['itemClassId'] for row in system.kanoa.quality.sheet.getItemClasses(chkShtInfo['chkShtId'])]
		if len(itemClassIds) > 0:
			log.info('adding checksheet item classes %s'%itemClassIds)
			system.kanoa.quality.sheet.addItemClasses(newChkShtId, itemClassIds, userId)	
	
		itemSetIds = [row['itemSetId'] for row in system.kanoa.quality.sheet.getItemSets(chkShtInfo['chkShtId'])]
		if len(itemSetIds) > 0:
			log.info('adding checksheet item sets %s'%itemSetIds)
		system.kanoa.quality.sheet.addItemSets(newChkShtId, itemSetIds, userId)		
		
		assetIds = [row['assetId'] for row in system.kanoa.quality.sheet.getAssets(chkShtInfo['chkShtId'])]
		if len(assetIds) > 0:
			log.info('adding checksheet assets %s'%assetIds)		
			system.kanoa.quality.sheet.addAssets(newChkShtId, assetIds, userId)
				
		#Now copy over chkItemImages
		from java.util import Base64
		for k,v in chkItemDict.items():
			imageData = system.kanoa.utilities.convertDatasetToJSON(system.kanoa.quality.config.getChkItemImageData({'chkItemId': k, 'includeThumbnail': True, 'includeImage': True}))
			for row in imageData:
				thumbnail = Base64.getDecoder().decode(row['thumbnail'])
				image = Base64.getDecoder().decode(row['image'])		
				chkItemImageId, msg = system.kanoa.quality.config.addChkItemImage(v, row['imageName'], row['imageType'], row['imageDescription'], image, thumbnail, 5)				
				if msg: log.error("addChkItemImage failed with %s"%msg)
			
	except java.lang.Exception, e:
		return None, e.cause	#e.getMessage()	
	
	return newChkShtId, None
##########################################################################################	
def updateSheetVersionState(masterChkShtId, chkShtId, chkShtVersionStateName, userId):
	'''
		This function updates the chkShtId version state i.e. to 'Released'. It handles the logic of creating copies, archiving, renaming etc.
		Valid state changes are...
		 -  None to 'Draft': Set ver # to 1
		 - 'Draft' to 'Released': Do nothing
		 - 'Released' to 'Draft': Do nothing
		 - 'Released' to 'In Revision': Duplicate checksheet. Increment ver #
		 - 'In Revision' to 'Released': Archive current released master, update master Ids to 'In Revision' chkShtId and set state to 'Release'
		 - 'Archived' to 'Released': Archive current released master, update existing checksheet to values from archived checksheet, increment ver #
		Args:
			masterChkShtId (int): Id of master check sheet
			chkShtId (int): Id of check sheet
			chkShtVersionStateName (string): i.e. 'Released'
			userId (int)
		Returns:
			# of records modified (int)
			message (string): None if success
		Updated:
			jfc 08/23/25 4:46pm Created
			jfc 11/09/25 4:46pm Set enabled to true when a chec sheet is released
	'''
	log = system.util.getLogger("kanoa_quality")
	log.info("updateSheetVersionState() called with %s %s %s"%(masterChkShtId, chkShtId, chkShtVersionStateName))

	chkShtVersionStatesDict = system.kanoa.utilities.convertDatasetToDict(system.kanoa.quality.sheet.getSheetVersionStates({}), 'chkShtVersionStateName', 'chkShtVersionStateId')
	if not chkShtVersionStatesDict.has_key(chkShtVersionStateName):
		msg = "Invalid chkShtVersionStateName passed %s"%chkShtVersionStateName
		log.info(msg)
		return None, msg

	chkShtVersions = system.kanoa.utilities.convertDatasetToJSON(system.kanoa.quality.sheet.getSheetVersionHistory({'masterChkShtId': masterChkShtId}))
	maxVersion = max(d['chkShtVersionNumber'] for d in chkShtVersions) if len(chkShtVersions) > 0 else 0

	if len(chkShtVersions) > 0:
		chkShtVersionInfo = chkShtVersions[0]
		chkShtVersionInfo['masterChkShtId'] = masterChkShtId
		chkShtVersionInfo['chkShtId'] = chkShtId
		chkShtVersionInfo['comment'] = 'User updated check sheet status'
		chkShtVersionInfo['chkShtVersionStateId'] = chkShtVersionStatesDict[chkShtVersionStateName]
	else:
		chkShtVersionInfo = {'masterChkShtId': masterChkShtId, 'chkShtId': chkShtId, 'chkShtVersionStateId': chkShtVersionStatesDict[chkShtVersionStateName], 'chkShtVersionStateName': None, 'comment': 'User updated check sheet status'}

	if chkShtVersionInfo['chkShtVersionStateName'] is None:
		chkShtVersionInfo['chkShtVersionNumber'] = 1
		chkShtVersionInfo['chkShtVersionStateName'] = chkShtVersionStateName		
		retVal, msg = system.kanoa.quality.sheet.addSheetVersionHistory(chkShtVersionInfo, userId)
	elif chkShtVersionInfo['chkShtVersionStateName'] == 'Draft' and chkShtVersionStateName == 'Released':
		chkShtVersionInfo['chkShtVersionStateName'] = chkShtVersionStateName
		retVal, msg = system.kanoa.quality.sheet.addSheetVersionHistory(chkShtVersionInfo, userId)
		system.kanoa.quality.sheet.updateSheetField(chkShtId, 'enabled', True, userId)
	elif chkShtVersionInfo['chkShtVersionStateName'] == 'Released' and chkShtVersionStateName == 'Draft':
		chkShtVersionInfo['chkShtVersionStateName'] = chkShtVersionStateName
		retVal, msg = system.kanoa.quality.sheet.addSheetVersionHistory(chkShtVersionInfo, userId)
	elif chkShtVersionInfo['chkShtVersionStateName'] == 'Released' and chkShtVersionStateName == 'In Revision':
		log.info("copySheet() called with %s"%chkShtId)
		chkShtName = "%s - %s"%(chkShtVersionInfo['chkShtName'], chkShtVersionStateName)
#		chkShtId, msg = system.kanoa.quality.sheet.copySheet({'chkShtId': chkShtId, 'chkShtName': chkShtName}, userId)
		chkShtId, msg = _kanoa_.quality.sheet.copySheet({'chkShtId': chkShtId, 'chkShtName': chkShtName}, userId)
		log.info("copySheet() return %s %s"%(chkShtId, msg))
		chkShtVersionInfo['chkShtId'] = chkShtId
		chkShtVersionInfo['chkShtVersionNumber'] = maxVersion + 1
		chkShtVersionInfo['chkShtVersionStateName'] = chkShtVersionStateName
		retVal, msg = system.kanoa.quality.sheet.addSheetVersionHistory(chkShtVersionInfo, userId)
	elif chkShtVersionInfo['chkShtVersionStateName'] == 'In Revision' and chkShtVersionStateName == 'Released':

		#All chkShtEvents and chkItemEvents will remain pointing to the check sheet Id they were taken against
		#May need to update analysis so that event data is returned for the masterId and the checkShtId
		verHistoryDict = system.kanoa.utilities.convertDatasetToDict(system.kanoa.quality.sheet.getSheetVersionHistory({'masterChkShtId': masterChkShtId}), 'chkShtVersionStateName', None)
		
		oldChkSht = verHistoryDict['Released']
		newChkSht = verHistoryDict['In Revision']

		# 1. Set the currently released check sheet (id) to 'Archived'
		log.info("Setting Released Check Sheet %s status to 'Archived'" %masterChkShtId)
		retVal, msg = system.kanoa.quality.sheet.updateSheetVersionHistoryField(oldChkSht['chkShtVersionHistoryId'], 'chkShtVersionStateId', chkShtVersionStatesDict['Archived'], userId)
		
		# 2. Rename the Archived checkSht
		chkShtName = "%s - %s"%(oldChkSht['chkShtName'],oldChkSht['chkShtVersionNumber'])
		log.info("Renaming Archived Check Sheet %s to %s"%(oldChkSht['chkShtId'], chkShtName))
		system.kanoa.quality.sheet.updateSheetField(oldChkSht['chkShtId'], 'chkShtName', chkShtName, userId)

		# 3. Set the 'In Revision check sheet (id) to 'Released'
		log.info("Setting 'In Revision' Check Sheet %s status to 'Released'" %newChkSht['chkShtId'])
		newChkSht['chkShtVersionStateId'] = chkShtVersionStatesDict['Released']
		retVal, msg = system.kanoa.quality.sheet.updateSheetVersionHistory(newChkSht, userId)	

		# 4. Rename the newly released checkSht
		log.info("Renaming 'Released' Check Sheet %s to %s"%(newChkSht['chkShtId'], oldChkSht['chkShtName']))
		system.kanoa.quality.sheet.updateSheetField(newChkSht['chkShtId'], 'chkShtName', oldChkSht['chkShtName'], userId)
		system.kanoa.quality.sheet.updateSheetField(newChkSht['chkShtId'], 'enabled', True, userId)

		# 5. Update the master Id
		for item in system.kanoa.utilities.convertDatasetToJSON(system.kanoa.quality.sheet.getSheetVersionHistory({'masterChkShtId': masterChkShtId})):
			log.info("Updating chkShtVersionHistoryId %s masterId to %s"%(item['chkShtVersionHistoryId'], newChkSht['chkShtId']))
			retVal, msg = system.kanoa.quality.sheet.updateSheetVersionHistoryField(item['chkShtVersionHistoryId'], 'masterChkShtId', newChkSht['chkShtId'], userId)

	else:
		chkShtVersionInfo['chkShtVersionStateName'] = chkShtVersionStateName
		retVal, msg = system.kanoa.quality.sheet.addSheetVersionHistory(chkShtVersionInfo, userId)
			
	return retVal, msg