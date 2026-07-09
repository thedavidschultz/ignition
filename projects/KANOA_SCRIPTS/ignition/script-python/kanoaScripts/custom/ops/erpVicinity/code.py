def getProductionOrders(paramsDict):
	'''
		stub to place custom ERP implementation
	'''	
		
	return 0
#################################################################################
def ERPSendBatchTickets(request):

	req_path = request['path']
	req_query = request['query']
	req_headers = request['headers']
	req_metadata = request['remote']
	req_body = request['body']
	
	log = system.util.getLogger('kanoa_ERP_IF')
	log.info('Received VCNTY_MES_SendBatch() POST with ' + str(req_body))

#	req_body = {
#					u'DisplayUnitOfMeasure': "EACH",
#					u'Material1': '', 
#					u'EndProductCodes': {
#						u'CleanScrap': '', 
#						u'Contamination': '', 
#						u'PETFines': '', 
#						u'Purge': 'BYP-SHT-CCPUR', 
#						u'FreeDrop': ''}
#					, u'PartNumber': 'SHT-INT-100CC180X520',
#					u'Cavities': 0.0,
#					u'ToolName': '',
#					u'TargetSetupTime': 0.0,
#					u'CountryRegionCode': None,
#					u'PackagingBOM': None,
#					u'PartWeight': 0.0,
#					u'CustomerName': None,
#					u'TargetCycleTime': 0.0,
#					u'BatchProcessed': 1,
#					u'StockingUnitOfMeasure': "EACH",
#					u'BatchNotes': "",
#					u'ThroughputLbsPerMin': 0.0,
#					u'BatchNumber': 'SH24-0038',
#					u'FeetPerMin': 0.0,
#					u'ZipCode': None,
#					u'Address2': None,
#					u'Quantity': 60000.0,
#					u'Address1': None,
#					u'City': None,
#					u'TargetCompletion': '20240220200000',
#					u'Thickness': 0.0,
#					u'BatchDescription': '',
#					u'SheetWidth': 0.0,
#					u'TargetStart': '20240219140000',
#					u'MachineName': 'Sheet Line 1',
#					u'State': None,
#					u'PartDescription': 'Master Roll (Bistro Bowl) .018" X 52"',
#					u'SegmentLength': 0.0
#				}

	res_code = 200
	res_headers = {}
	res_content = {'status': "Good"}
	
	woName = req_body['BatchNumber']
	if (woName or None) is None: return	

	import java.lang
	userId = system.kanoa.security.getIDPUserId({'id': 'ERP', 'userName': 'ERP'})
			
	try:
		product = req_body['PartNumber']
		reqdQty = req_body['Quantity']
		targetStart = system.date.parse(req_body['TargetStart'], 'yyyyMMddhhmmss')		
		dueDate = system.date.parse(req_body['TargetCompletion'], 'yyyyMMddhhmmss')
		machineName = req_body['MachineName']
		
		uom = req_body['DisplayUnitOfMeasure'].lower() if req_body.has_key('DisplayUnitOfMeasure') and req_body['DisplayUnitOfMeasure'] is not None else 'units'
#		uom ='lbs' if 'Sheet Line' in machineName else 'units'

		notes = req_body['BatchNotes'] if req_body.has_key('BatchNotes') else None
	
		assetAttributes = system.kanoa.utilities.convertDatasetToJSON(system.kanoa.asset.getAssetAttributes({}))
		attrInfo = {item['assetAttrValue']: item['assetId'] for item in assetAttributes if item['assetAttrName'] == 'erpMachineName'}
		assetId = attrInfo[machineName] if attrInfo.has_key(machineName) else None 
	
		itemUnitId = system.kanoa.utilities.getFieldValue('itemUnitId', system.kanoa.item.getItemUnits({'itemUnitName': uom}))
		if itemUnitId is None: itemUnitId = system.kanoa.item.addItemUnit(uom, userId)
		 
		workOrderSourceId = system.kanoa.utilities.getFieldValue('workOrderSourceId', system.kanoa.order.getProductionOrderSource({'workOrderSourceName': 'ERP'}))				
		modeId = system.kanoa.utilities.getFieldValue('modeId', system.kanoa.asset.getAssetModes({'assetId': assetId, 'modeName': 'Production'})) if assetId else None	
		woStates = system.kanoa.utilities.convertDatasetToDict(system.kanoa.order.getProductionOrderStates({}), 'workOrderStatusName', 'workOrderStatusId')
		
		itemInfo = system.kanoa.utilities.convertDatasetRowToJSON(system.kanoa.item.getItems({'itemName': product}),0)
		itemDescription = req_body['PartDescription'] if req_body.has_key('PartDescription') else 'created by ERP I/F'
		if itemInfo['itemId'] is None:
			log.info("This item wasn't found. Adding new product %s"%product)			
			paramsDict = {'itemName': product, 'itemDescription': itemDescription, 'itemClassId': None, 'itemColor': None, 'enabled': True}
			itemInfo['itemId'] = system.kanoa.item.addItem(paramsDict, userId)
		elif itemDescription != itemInfo['itemDescription']:
			try:					
				log.info("Updating %s description %s"%(product, itemDescription))
				system.kanoa.item.updateItemField(itemInfo['itemId'], 'itemDescription', itemDescription, userId)
			except:
				log.error("failed to update description")
				
		woInfo = system.kanoa.utilities.convertDatasetRowToJSON(system.kanoa.order.getProductionOrders({'workOrderName': woName}),0)
		if woInfo['workOrderId'] is None:
			woInfo = {'workOrderName': woName, 'modeId': modeId, 'itemId': itemInfo['itemId'], 'itemUnitId': itemUnitId, 'assetId': assetId, 'workOrderSourceId':workOrderSourceId, 'reqdQty': reqdQty, 'dueDate': dueDate, 'workOrderStatusId': woStates['Released'], 'note': notes}
			woInfo['workOrderId'] = system.kanoa.order.addProductionOrder(woInfo, userId)
			log.info("addProductionOrder() returned %s"%woInfo['workOrderId'])

			if assetId:	#Only schedule if this is new and we have an assetId for it
				scheduleBlockInfo = {'scheduleBlockName': 'ERP Production Order', 'assetId': assetId, 'itemId': itemInfo['itemId'], 'workOrderId': woInfo['workOrderId'], 'scheduledQty': reqdQty, 'modeId': modeId, 'startDate': targetStart, 'endDate': dueDate, 'notes': None, 'rruleStr': None, 'color': None}
				scheduleBlockId = system.kanoa.schedule.addScheduleBlock(scheduleBlockInfo, userId)
				log.info("addScheduleBlock() returned %s"%scheduleBlockId)			
			
		else:
			woInfo['reqdQty'] = reqdQty
			woInfo['dueDate'] = dueDate
			woInfo['assetId'] = assetId
			woInfo['itemId'] = itemInfo['itemId']
			woInfo['note'] = notes
			woInfo['itemUnitId'] = itemUnitId
			retVal = system.kanoa.order.updateProductionOrder(woInfo, userId)
			log.info("updateProductionOrder() returned %s"%retVal)
	
		try:
			system.kanoa.order.addProductionMetaOrder({'workOrderId': woInfo['workOrderId'], 'metaDataName': 'apiBody', 'metaDataValue': system.util.jsonEncode(req_body)}, userId)
		except java.lang.Exception, e:
			log.warn("Couldn't add meta data %s %s"%(woName, e.cause))		

	except java.lang.Exception, e:
		log.error('Failed to add ERP Batch ticket %s %s'%(woName, e.cause))
		res_code = 403
		res_headers = {}
		res_content = {'status': "Bad", 'msg': e.cause}
	
	return {'code': res_code, 'headers': res_headers, 'content': res_content}
#################################################################################
def addBatchTransactions():

	body = {
			"FacilityID": "MAIN",
			"BatchNumber": "SH24-0021",
			"UserID": "MES_USER",
			"TransactionDate": "2024-01-23T22:36:33.772Z",
			"GPBatchNumber": "",
			"VicinityBatchTransactions": 
			[
				{
					"TransactionSource": "EndItem",
					"LineIDNumber": 12,
					"ComponentID": "SHT-INT-100CC470X530",
					"SiteID": "RPE",
					"BinNumber": "QC HOLD",
					"UOM": "",
					"TransactionLots": 
					[
						{
							"LotNumber": "SH24-0021-01",
							"ReceiptDate": "2024-01-23T22:36:33.772Z",
							"ReceiptDateSequenceNumber": 0,
							"MfgDate": "2024-01-23T22:36:33.772Z",
							"ExpirationDate": "2024-01-23T22:36:33.772Z",
							"LotQuantity": {"DecimalDigits": 5, "Value": 3602},
						}
					],
				"TransactionQuantity": {"DecimalDigits": 5, "Value": 3602}
				}
			]
		}
	
	result = system.ws.runWebService('AddBatchTransactions', None, {'Content-type': "application/json"}, body)
	return result
#################################################################################	
def postTransactionToVicinity():

	url = 'https://vicinityweb_rplanet.cloud.vicinitybrew.com/VicinityWebRPlanetPublic/api/vicinityservice/batch/addtransaction?companyID=rplanetBC'
	postParams = {
			"FacilityID": "MAIN",
			"BatchNumber": "SH24-0001",
			"UserID": "WS_TESTBED",
			"VicinityBatchTransactions": 
			[
				{
					"ComponentID": "SHT-INT-100CC180X520",
					"SiteID": "RPE",
					"BinNumber": "MRW-01",
					"UOM": "",
					"TransactionLots": 
					[
						{
							"LotNumber": "SH24-0001-02",
							"LotQuantity": {"DecimalDigits": 5, "Value": 3500.0}
						}
					],
					"TransactionQuantity": {"DecimalDigits": 5, "Value": 3500.0},
					"LineIDNumber": 12
				}
			]
		}
		
	response = system.net.httpPost(url, contentType= 'application/json', postData=postParams, username=None, password=None, bypassCertValidation=True, throwOnError=True)	
	
	return response	